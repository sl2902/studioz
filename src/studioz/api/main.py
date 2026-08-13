import asyncio
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from studioz.api.jobs import Job, JobStatus, JOBS
from studioz.ledger import ledger
from studioz.narration_pipeline import run_narration_pipeline
from studioz.pipeline import run_studioz_pipeline, generate_storyboard_images, validate_and_rewrite_prompts
from studioz.agents.director import agent_director
from studioz.pipeline import get_storyboard_plan, enforce_runtime_target, _safe_title
from studioz.prompts import load_personas
from studioz.schemas import PitchBrief, Storyboard, ScriptTreatment, ExecutiveReview, GroundingCitations


# Build dynamic Literal types from personas.yaml at module load time
_personas = load_personas()
_SCREENWRITER_KEYS = tuple(_personas["screenwriter"].keys())
_DIRECTOR_KEYS = tuple(_personas["director"].keys())
ScreenwriterPersona = Literal[_SCREENWRITER_KEYS]  # type: ignore[valid-type]
DirectorPersona = Literal[_DIRECTOR_KEYS]  # type: ignore[valid-type]


app = FastAPI(title="StudioZ API", version="0.1.0")

# CORS — permissive for dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for generated assets
outputs_dir = Path("outputs")
outputs_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(outputs_dir)), name="static")


def _path_to_url(file_path: str | None) -> str | None:
    """Convert a local file path to a servable static URL."""
    if file_path is None:
        return None
    p = Path(file_path)
    try:
        relative = p.relative_to("outputs")
        return f"/static/{relative}"
    except ValueError:
        return file_path


def _storyboard_to_dict(storyboard: Storyboard) -> dict:
    """Convert storyboard to dict with URLs instead of file paths."""
    data = storyboard.model_dump()
    for frame in data["frames"]:
        frame["image_url"] = _path_to_url(frame.get("image_path"))
    return data


# ============================================================
# Request models (persona fields use dynamic Literal for auto-validation)
# ============================================================

class PitchRequest(BaseModel):
    pitch: str = Field(min_length=10, description="The film pitch/premise (at least 10 characters)")
    film_type: Literal["feature", "short"] = "feature"
    target_runtime_minutes: int | None = Field(default=None, gt=0, description="Target runtime in minutes (must be positive if set)")
    screenwriter_persona: ScreenwriterPersona = _SCREENWRITER_KEYS[0]  # type: ignore[valid-type]
    director_persona: DirectorPersona = _DIRECTOR_KEYS[0]  # type: ignore[valid-type]
    force: bool = False


class RegenerateStoryboardRequest(BaseModel):
    director_persona: DirectorPersona  # type: ignore[valid-type]


# ============================================================
# Background task runners
# ============================================================

async def _run_pitch_pipeline(job_id: str, request: PitchRequest):
    """Run the full pipeline as a background task."""
    job = JOBS[job_id]
    job.status = JobStatus.RUNNING
    job.current_stage = "starting"

    try:
        brief = PitchBrief(
            pitch=request.pitch,
            film_type=request.film_type,
            target_runtime_minutes=request.target_runtime_minutes,
        )

        job.current_stage = "pipeline"
        result = await run_studioz_pipeline(
            brief,
            screen_writer_persona=request.screenwriter_persona,
            director_persona=request.director_persona,
            force=request.force,
            render_video=False,
        )

        if result is None:
            job.status = JobStatus.FAILED
            job.error = "Pipeline returned None (exception during execution)"
            return

        treatment, exec_review, storyboard, citations = result

        job.status = JobStatus.COMPLETED
        job.current_stage = "completed"
        job.result = {
            "treatment": treatment.model_dump(),
            "executive_review": exec_review.model_dump(),
            "storyboard": _storyboard_to_dict(storyboard) if storyboard else None,
            "grounding_citations": citations.model_dump() if citations else None,
            "ledger_summary": ledger.summary(),
            # Cache for regeneration
            "_cached_treatment": treatment.model_dump(),
            "_cached_review": exec_review.model_dump(),
            "_cached_citations": citations.model_dump() if citations else None,
            "_force": request.force,
            "_greenlit": exec_review.greenlight,
        }

    except Exception as e:
        logger.exception("Pipeline failed for job {}", job_id)
        job.status = JobStatus.FAILED
        job.error = str(e)


async def _run_render_video(job_id: str, storyboard: Storyboard):
    """Run narration + TTS + video assembly as a background task."""
    job = JOBS[job_id]
    job.status = JobStatus.RUNNING
    job.current_stage = "narration_and_video"

    try:
        video_path = await run_narration_pipeline(storyboard)
        if video_path:
            job.status = JobStatus.COMPLETED
            job.current_stage = "completed"
            job.result = {"video_url": _path_to_url(video_path)}
        else:
            job.status = JobStatus.FAILED
            job.error = "Video rendering returned None"

    except Exception as e:
        logger.exception("Video rendering failed for job {}", job_id)
        job.status = JobStatus.FAILED
        job.error = str(e)


async def _run_regenerate_storyboard(
    job_id: str,
    treatment: ScriptTreatment,
    exec_review: ExecutiveReview,
    citations: GroundingCitations | None,
    director_persona: str,
):
    """Re-run only Director + image generation with cached upstream results."""
    job = JOBS[job_id]
    job.status = JobStatus.RUNNING
    job.current_stage = "director"

    try:
        # Reset ledger for this sub-run
        ledger._entries = []

        beats = get_storyboard_plan(treatment.estimated_runtime_minutes)
        storyboard, image_style = await agent_director(
            treatment, exec_review, director_persona, beats=beats
        )

        # Upstream color validation
        storyboard = await validate_and_rewrite_prompts(storyboard, image_style)

        job.current_stage = "image_generation"
        storyboard = await generate_storyboard_images(storyboard, image_style=image_style)

        job.status = JobStatus.COMPLETED
        job.current_stage = "completed"
        job.result = {
            "treatment": treatment.model_dump(),
            "executive_review": exec_review.model_dump(),
            "storyboard": _storyboard_to_dict(storyboard),
            "grounding_citations": citations.model_dump() if citations else None,
            "ledger_summary": ledger.summary(),
            "_cached_treatment": treatment.model_dump(),
            "_cached_review": exec_review.model_dump(),
            "_cached_citations": citations.model_dump() if citations else None,
            "_force": True,
            "_greenlit": exec_review.greenlight,
        }

    except Exception as e:
        logger.exception("Storyboard regeneration failed for job {}", job_id)
        job.status = JobStatus.FAILED
        job.error = str(e)


# ============================================================
# Endpoints
# ============================================================

class PersonaOption(BaseModel):
    key: str
    name: str
    title: str


class PersonaOptions(BaseModel):
    screenwriter: list[PersonaOption]
    director: list[PersonaOption]



@app.get("/api/personas")
async def get_personas() -> PersonaOptions:
    """Return available persona options for screenwriter and director roles."""
    catalog = load_personas()  # Re-read live so changes are reflected without restart
    screenwriter_options = []
    for key, data in catalog.get("screenwriter", {}).items():
        screenwriter_options.append(PersonaOption(
            key=key,
            name=data.get("name", key),
            title=data.get("title", ""),
        ))
    director_options = []
    for key, data in catalog.get("director", {}).items():
        director_options.append(PersonaOption(
            key=key,
            name=data.get("name", key),
            title=data.get("title", ""),
        ))
    return PersonaOptions(screenwriter=screenwriter_options, director=director_options)


@app.post("/api/pitch")
async def create_pitch(request: PitchRequest):
    """Start a new pipeline run. Returns job_id immediately."""
    job_id = str(uuid.uuid4())
    job = Job(job_id=job_id)
    JOBS[job_id] = job
    asyncio.create_task(_run_pitch_pipeline(job_id, request))
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Poll job status."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    # Return without internal cache fields
    response = job.model_dump()
    if response.get("result"):
        response["result"] = {
            k: v for k, v in response["result"].items()
            if not k.startswith("_")
        }
    return response


@app.post("/api/render-video/{job_id}")
async def render_video(job_id: str):
    """Start video rendering for a completed job's storyboard."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    source_job = JOBS[job_id]
    if source_job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job is not completed")
    if not source_job.result or not source_job.result.get("storyboard"):
        raise HTTPException(status_code=400, detail="Job has no storyboard to render")

    # Load the storyboard from the saved JSON (uses actual file paths, not URLs)
    storyboard_data = source_job.result["storyboard"]
    # Reconstruct with file paths (reverse URL conversion)
    for frame in storyboard_data["frames"]:
        if frame.get("image_url") and frame["image_url"].startswith("/static/"):
            frame["image_path"] = "outputs/" + frame["image_url"][len("/static/"):]
    storyboard = Storyboard.model_validate(storyboard_data)

    # Create a new job for video rendering
    video_job_id = str(uuid.uuid4())
    video_job = Job(job_id=video_job_id)
    JOBS[video_job_id] = video_job
    asyncio.create_task(_run_render_video(video_job_id, storyboard))
    return {"job_id": video_job_id}


@app.post("/api/regenerate-storyboard/{job_id}")
async def regenerate_storyboard(job_id: str, request: RegenerateStoryboardRequest):
    """Re-run Director + image generation with a different persona, reusing cached upstream results."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    source_job = JOBS[job_id]
    if source_job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Source job is not completed")
    if not source_job.result:
        raise HTTPException(status_code=400, detail="Source job has no results")

    cached_treatment = source_job.result.get("_cached_treatment")
    cached_review = source_job.result.get("_cached_review")
    if not cached_treatment or not cached_review:
        raise HTTPException(
            status_code=400,
            detail="Source job doesn't have cached treatment/review for regeneration"
        )

    # Reconstruct the cached objects
    treatment = ScriptTreatment.model_validate(cached_treatment)
    exec_review = ExecutiveReview.model_validate(cached_review)
    cached_citations = source_job.result.get("_cached_citations")
    citations = GroundingCitations.model_validate(cached_citations) if cached_citations else None

    # Create a new job
    new_job_id = str(uuid.uuid4())
    new_job = Job(job_id=new_job_id, regenerated_from=job_id)
    JOBS[new_job_id] = new_job

    asyncio.create_task(_run_regenerate_storyboard(
        new_job_id, treatment, exec_review, citations, request.director_persona
    ))
    return {"job_id": new_job_id}


@app.get("/api/health")
async def health():
    return {"status": "ok"}

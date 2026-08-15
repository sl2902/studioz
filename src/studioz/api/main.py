import asyncio
import hashlib
import json
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


# Request-level cache: maps deterministic request hash -> completed job_id
REQUEST_CACHE: dict[str, str] = {}


def _compute_request_key(request: "PitchRequest") -> str:
    """Compute a stable hash from the request body (excluding bypass_cache)."""
    data = request.model_dump(exclude={"bypass_cache"})
    canonical = json.dumps(data, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


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


MANIFESTS_DIR = Path("outputs/jobs")


GOLDEN_POINTER_PATH = Path("demo_results/golden_job_id.txt")


def _persist_job_manifest(job_id: str, result: dict) -> None:
    """Auto-write a job's result to disk as a manifest for durability."""
    manifest_dir = MANIFESTS_DIR / job_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    # Write public-facing result (strip internal cache fields)
    public_result = {k: v for k, v in result.items() if not k.startswith("_")}
    manifest_path.write_text(json.dumps(public_result, indent=2, default=str))
    logger.info("Job manifest persisted: {}", manifest_path)

    # Bootstrap auto-golden: if no golden pointer exists yet, set this job as golden
    if not GOLDEN_POINTER_PATH.exists():
        GOLDEN_POINTER_PATH.parent.mkdir(exist_ok=True)
        GOLDEN_POINTER_PATH.write_text(job_id)
        logger.success("Bootstrap: auto-set golden demo pointer -> {} (first completed job)", job_id[:8])


def _load_job_manifest(job_id: str) -> dict | None:
    """Load a job manifest from disk (fallback when not in memory)."""
    manifest_path = MANIFESTS_DIR / job_id / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return None


def _storyboard_to_dict(storyboard: Storyboard) -> dict:
    """Convert storyboard to dict with URLs instead of file paths."""
    data = storyboard.model_dump()
    for frame in data["frames"]:
        frame["image_url"] = _path_to_url(frame.get("image_path"))
    return data


# Request models (persona fields use dynamic Literal for auto-validation)

class PitchRequest(BaseModel):
    pitch: str = Field(min_length=10, description="The film pitch/premise (at least 10 characters)")
    film_type: Literal["feature", "short"] = "feature"
    target_runtime_minutes: int | None = Field(default=None, gt=0, description="Target runtime in minutes (must be positive if set)")
    screenwriter_persona: ScreenwriterPersona = _SCREENWRITER_KEYS[0]  # type: ignore[valid-type]
    director_persona: DirectorPersona = _DIRECTOR_KEYS[0]  # type: ignore[valid-type]
    force: bool = False
    bypass_cache: bool = Field(default=False, description="If true, skip cache and force a fresh pipeline run")


class RegenerateStoryboardRequest(BaseModel):
    director_persona: DirectorPersona  # type: ignore[valid-type]


# Background task runners

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

        job.current_stage = "starting"
        result = await run_studioz_pipeline(
            brief,
            screen_writer_persona=request.screenwriter_persona,
            director_persona=request.director_persona,
            force=request.force,
            render_video=False,
            on_stage=lambda stage: setattr(job, 'current_stage', stage),
            job_id=job_id,
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
            "ledger_entries": ledger.to_dict_list(),
            "ledger_totals": ledger.totals(),
            # Cache for regeneration
            "_cached_treatment": treatment.model_dump(),
            "_cached_review": exec_review.model_dump(),
            "_cached_citations": citations.model_dump() if citations else None,
            "_force": request.force,
            "_greenlit": exec_review.greenlight,
        }

        # Store in request cache for future identical submissions
        request_key = _compute_request_key(request)
        REQUEST_CACHE[request_key] = job_id

        # Auto-persist manifest to disk
        _persist_job_manifest(job_id, job.result)

    except Exception as e:
        logger.exception("Pipeline failed for job {}", job_id)
        job.status = JobStatus.FAILED
        job.error = str(e)


async def _run_render_video(
    job_id: str,
    storyboard: Storyboard,
    parent_job_id: str | None = None,
    estimated_runtime_minutes: int = 0,
    greenlit: bool = True,
    force_used: bool = False,
    rejection_summary: str | None = None,
):
    """Run narration + TTS + video assembly as a background task."""
    job = JOBS[job_id]
    job.status = JobStatus.RUNNING
    job.current_stage = "narration"

    # Mirror status to parent
    parent_job = JOBS.get(parent_job_id) if parent_job_id else None
    if parent_job:
        parent_job.video_status = JobStatus.RUNNING

    try:
        video_path = await run_narration_pipeline(
            storyboard,
            on_stage=lambda stage: setattr(job, 'current_stage', stage),
            job_id=job_id,
            estimated_runtime_minutes=estimated_runtime_minutes,
            greenlit=greenlit,
            force_used=force_used,
            rejection_summary=rejection_summary,
        )
        if video_path:
            video_url = _path_to_url(video_path)
            job.status = JobStatus.COMPLETED
            job.current_stage = "completed"
            job.result = {"video_url": video_url}
            _persist_job_manifest(job_id, job.result)
            # Mirror to parent
            if parent_job:
                parent_job.video_status = JobStatus.COMPLETED
                parent_job.video_url = video_url
                # Re-persist parent manifest with video URL
                if parent_job.result:
                    parent_job.result["video_url"] = video_url
                    _persist_job_manifest(parent_job_id, parent_job.result)
        else:
            job.status = JobStatus.FAILED
            job.error = "Video rendering returned None"
            if parent_job:
                parent_job.video_status = JobStatus.FAILED

    except Exception as e:
        logger.exception("Video rendering failed for job {}", job_id)
        job.status = JobStatus.FAILED
        job.error = str(e)
        if parent_job:
            parent_job.video_status = JobStatus.FAILED


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
        storyboard = await generate_storyboard_images(storyboard, image_style=image_style, job_id=job_id)

        job.status = JobStatus.COMPLETED
        job.current_stage = "completed"
        job.result = {
            "treatment": treatment.model_dump(),
            "executive_review": exec_review.model_dump(),
            "storyboard": _storyboard_to_dict(storyboard),
            "grounding_citations": citations.model_dump() if citations else None,
            "ledger_summary": ledger.summary(),
            "ledger_entries": ledger.to_dict_list(),
            "ledger_totals": ledger.totals(),
            "_cached_treatment": treatment.model_dump(),
            "_cached_review": exec_review.model_dump(),
            "_cached_citations": citations.model_dump() if citations else None,
            "_force": True,
            "_greenlit": exec_review.greenlight,
        }

        # Auto-persist manifest to disk
        _persist_job_manifest(job_id, job.result)

    except Exception as e:
        logger.exception("Storyboard regeneration failed for job {}", job_id)
        job.status = JobStatus.FAILED
        job.error = str(e)


# Endpoints

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
    """Start a new pipeline run. Returns job_id immediately, or cached result if available."""
    # Cache check
    if not request.bypass_cache:
        request_key = _compute_request_key(request)
        cached_job_id = REQUEST_CACHE.get(request_key)
        if cached_job_id and cached_job_id in JOBS:
            cached_job = JOBS[cached_job_id]
            if cached_job.status == JobStatus.COMPLETED:
                logger.info("Cache hit for request — returning job {}", cached_job_id[:8])
                return {"job_id": cached_job_id, "cached": True}

    job_id = str(uuid.uuid4())
    job = Job(job_id=job_id)
    JOBS[job_id] = job
    asyncio.create_task(_run_pitch_pipeline(job_id, request))
    return {"job_id": job_id, "cached": False}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Poll job status. Falls back to disk manifest if not in memory."""
    if job_id in JOBS:
        job = JOBS[job_id]
        response = job.model_dump()
        if response.get("result"):
            response["result"] = {
                k: v for k, v in response["result"].items()
                if not k.startswith("_")
            }
        return response

    # Fallback: check for persisted manifest on disk
    manifest = _load_job_manifest(job_id)
    if manifest:
        return {
            "job_id": job_id,
            "status": "completed",
            "created_at": None,
            "result": manifest,
            "error": None,
            "current_stage": "completed",
            "regenerated_from": None,
            "video_job_id": None,
            "video_url": manifest.get("video_url"),
            "video_status": "completed" if manifest.get("video_url") else None,
        }

    raise HTTPException(status_code=404, detail="Job not found")


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

    # Guard: block if a render is already in progress
    if source_job.video_status in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(status_code=409, detail="Video render already in progress")

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

    # Track on parent job
    source_job.video_job_id = video_job_id
    source_job.video_status = JobStatus.PENDING
    source_job.video_url = None

    # Extract context for disclaimer cards
    treatment_data = source_job.result.get("_cached_treatment") or source_job.result.get("treatment", {})
    review_data = source_job.result.get("_cached_review") or source_job.result.get("executive_review", {})
    runtime_min = treatment_data.get("estimated_runtime_minutes", 0)
    is_greenlit = review_data.get("greenlight", True)
    was_forced = source_job.result.get("_force", False)
    reject_summary = review_data.get("summary", "") if not is_greenlit else None

    asyncio.create_task(_run_render_video(
        video_job_id, storyboard, parent_job_id=job_id,
        estimated_runtime_minutes=runtime_min,
        greenlit=is_greenlit,
        force_used=was_forced,
        rejection_summary=reject_summary,
    ))
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


@app.post("/api/demo/set-golden/{job_id}")
async def set_golden_demo(job_id: str):
    """Set a job as the golden demo by writing a pointer file."""
    # Verify manifest exists (either in memory or on disk)
    manifest = _load_job_manifest(job_id)
    if not manifest:
        # Check if it's in memory and hasn't been persisted yet
        if job_id in JOBS and JOBS[job_id].status == JobStatus.COMPLETED and JOBS[job_id].result:
            _persist_job_manifest(job_id, JOBS[job_id].result)
            manifest = _load_job_manifest(job_id)

    if not manifest:
        raise HTTPException(status_code=404, detail=f"No manifest found for job '{job_id}'. Job must be completed first.")

    # Write the pointer
    GOLDEN_POINTER_PATH.parent.mkdir(exist_ok=True)
    GOLDEN_POINTER_PATH.write_text(job_id)

    title = manifest.get("treatment", {}).get("title", "Unknown")
    logger.success("Golden demo pointer set: {} -> {}", job_id[:8], title)
    return {
        "status": "set",
        "job_id": job_id,
        "title": title,
        "has_storyboard": manifest.get("storyboard") is not None,
        "has_video": manifest.get("video_url") is not None,
    }


@app.get("/api/demo/golden")
async def get_golden_demo():
    """Load the golden demo result via the pointer + manifest."""
    if not GOLDEN_POINTER_PATH.exists():
        raise HTTPException(status_code=404, detail="No golden demo set. Call POST /api/demo/set-golden/{job_id} first.")

    golden_job_id = GOLDEN_POINTER_PATH.read_text().strip()
    if not golden_job_id:
        raise HTTPException(status_code=404, detail="Golden pointer file is empty.")

    manifest = _load_job_manifest(golden_job_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Golden job '{golden_job_id}' manifest not found on disk.")

    return manifest


@app.get("/api/demo/explainer-audio")
async def get_explainer_audio():
    """Return list of explainer step audio URLs (for auto-advance playback)."""
    from studioz.generate_demo_audio import EXPLAINER_STEPS, EXPLAINER_CACHE_DIR
    steps = []
    for step in EXPLAINER_STEPS:
        wav_path = EXPLAINER_CACHE_DIR / f"{step['id']}.wav"
        audio_url = f"/static/_assets/explainer_voice/{step['id']}.wav" if wav_path.exists() else None
        steps.append({
            "id": step["id"],
            "text": step["text"],
            "audio_url": audio_url,
        })
    return {"steps": steps, "all_cached": all(s["audio_url"] for s in steps)}


@app.get("/api/demo/walkthrough-audio")
async def get_walkthrough_audio():
    """Return the golden demo walkthrough audio URL."""
    from studioz.generate_demo_audio import DEMO_WALKTHROUGH_DIR
    pointer_path = Path("demo_results/golden_job_id.txt")
    if not pointer_path.exists():
        raise HTTPException(status_code=404, detail="No golden demo set")
    golden_job_id = pointer_path.read_text().strip()
    wav_path = DEMO_WALKTHROUGH_DIR / f"{golden_job_id}.wav"
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail="Walkthrough audio not generated yet. Run: python -m studioz.generate_demo_audio")
    return {
        "audio_url": f"/static/_assets/demo_walkthrough/{golden_job_id}.wav",
        "job_id": golden_job_id,
    }


@app.post("/api/demo/generate-audio")
async def trigger_demo_audio_generation():
    """Generate/cache all demo audio (explainer steps + walkthrough). One-time action."""
    from studioz.generate_demo_audio import generate_explainer_audio, generate_demo_walkthrough
    await generate_explainer_audio()
    await generate_demo_walkthrough()
    return {"status": "generated"}


@app.get("/api/health")
async def health():
    return {"status": "ok"}

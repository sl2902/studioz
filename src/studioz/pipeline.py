import asyncio
import re
import time
from argparse import ArgumentParser
from pathlib import Path

from google.genai import types
from loguru import logger

from studioz.agents import (
    agent_committee_member,
    agent_consensus,
    agent_director,
    agent_screenwriter,
)
from studioz.clients.inspector import inspect_frame
from studioz.clients.parallel_search import fetch_parallel_grounding
from studioz.clients.image_client import generate_frame_image
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.ledger import ledger, LedgerEntry, estimate_text_cost
from studioz.narration_pipeline import run_narration_pipeline
from studioz.schemas import PitchBrief, ScriptTreatment, Storyboard


OUTPUTS_DIR = Path("outputs/storyboard")

# ============================================================
# Pre-generation prompt reviewer
# ============================================================

# Fast regex patterns for known bad patterns (free, no LLM call)
_BANNED_COLOR_PATTERN = re.compile(
    r"\b(red|green|blue|orange|yellow|purple|pink|colou?r(?:ed|ful)?)\b",
    re.IGNORECASE,
)
_TEMPORAL_PATTERN = re.compile(
    r"\b(initially|then|after(?:ward)?|replaced by|transforms into|becomes|eventually|later|suddenly)\b",
    re.IGNORECASE,
)
_PARENTHESIZED_NAME_PATTERN = re.compile(
    r"\([A-Z][A-Za-z._\-' ]{1,20}\)",
)


def _fast_regex_check(imagen_prompt: str, image_style: str) -> list[str]:
    """Run fast, free regex checks. Returns list of issues found (empty if clean)."""
    issues = []
    if image_style == "stick_figure" and _BANNED_COLOR_PATTERN.search(imagen_prompt):
        matches = _BANNED_COLOR_PATTERN.findall(imagen_prompt)
        issues.append(f"Color words in monochrome-only style: {matches}")
    temporal = _TEMPORAL_PATTERN.findall(imagen_prompt)
    if temporal:
        issues.append(f"Temporal-sequence language (can't depict in static image): {temporal}")
    names = _PARENTHESIZED_NAME_PATTERN.findall(imagen_prompt)
    if names:
        issues.append(f"Parenthesized names (will render as text labels): {names}")
    return issues


async def _llm_review_prompt(imagen_prompt: str, style_constraints: str) -> tuple[bool, list[str], str | None]:
    """
    Holistic LLM-based prompt review against style constraints.
    Returns (passed, issues, corrected_prompt_or_none).
    """
    from studioz.schemas import PromptReviewResult
    review_instruction = (
        "You are a quality reviewer for image generation prompts. Check this prompt "
        "against the following constraints and determine if it would produce a valid image.\n\n"
        f"CONSTRAINTS:\n{style_constraints}\n\n"
        "COMMON VIOLATIONS TO CHECK:\n"
        "- Any text, labels, words, or legible writing described\n"
        "- Temporal sequences (before/after, transformations) in a single image\n"
        "- Character names that would render as visible text labels\n"
        "- Color references when monochrome is required\n"
        "- 'Text panels', 'documents', 'scripts' that would render as text\n\n"
        "If the prompt violates ANY constraint, provide a corrected version that "
        "fixes all violations while preserving the same scene content."
    )
    try:
        response = await client.aio.models.generate_content(
            model=settings.model_fast,
            contents=f"{review_instruction}\n\nPROMPT TO REVIEW:\n{imagen_prompt}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PromptReviewResult,
                temperature=0.1,
            ),
        )
        result: PromptReviewResult = response.parsed
        return result.passed, result.issues, result.corrected_prompt
    except Exception as e:
        logger.warning("LLM prompt review failed ({}), treating as pass", e)
        return True, [], None


async def _rewrite_prompt_for_issues(
    imagen_prompt: str, issues: list[str], style_constraints: str
) -> str:
    """
    Rewrite an image prompt to fix specific issues.
    Uses a cheap text model to incorporate feedback without losing the original intent.
    """
    issues_text = "\n".join(f"- {issue}" for issue in issues)
    rewrite_instruction = (
        "You are fixing an image generation prompt. "
        "The following issues were found:\n\n"
        f"{issues_text}\n\n"
        f"Style constraints that MUST be respected:\n{style_constraints}\n\n"
        "Rewrite the prompt to avoid ALL listed issues while preserving "
        "the same scene content and composition. "
        "Return ONLY the rewritten prompt, nothing else."
    )
    try:
        response = await client.aio.models.generate_content(
            model=settings.model_fast,
            contents=f"{rewrite_instruction}\n\nOriginal prompt:\n{imagen_prompt}",
            config=types.GenerateContentConfig(temperature=0.1),
        )
        rewritten = response.text.strip()
        if not rewritten or len(rewritten) < 20:
            return imagen_prompt
        return rewritten
    except Exception as e:
        logger.warning("Prompt rewrite failed ({}), keeping original", e)
        return imagen_prompt


async def validate_and_rewrite_prompts(storyboard: Storyboard, image_style: str) -> Storyboard:
    """
    Pre-generation prompt reviewer. Catches violations BEFORE spending on image generation.

    Two layers applied to ALL styles (not just stick_figure):
    1. Fast regex pre-checks (free): color, temporal, parenthesized names
    2. LLM holistic review (cheap ~$0.003): semantic check against full constraint set

    Runs after Director generates Storyboard, before any generate_frame_image call.
    """
    if image_style == "stick_figure":
        style_constraints = (
            "Zero legible text — no labels, names, words, documents, or text panels. "
            "100% black lines on pure white background — no color anywhere. "
            "xkcd-style minimalist stick figures. Single static moment only. "
            "Max 2-3 figures, one clear focal action. No parenthesized names."
        )
    else:
        style_constraints = (
            "No on-screen text, captions, logos, or watermarks. "
            "No character names as visible labels. "
            "Single static moment — no temporal sequences. "
            "Pure visual scene description."
        )

    for frame in storyboard.frames:
        prompt = frame.imagen_prompt

        # Layer 1: Fast regex checks (free)
        regex_issues = _fast_regex_check(prompt, image_style)

        if regex_issues:
            # Regex caught issues — rewrite immediately (skip LLM review)
            logger.info("Frame {} regex pre-check: {}", frame.frame_number, regex_issues)
            ledger.record(LedgerEntry(
                step_name=f"review_prompt_frame_{frame.frame_number}",
                latency_seconds=0.0,
                estimated_cost_usd=0.0,
                model="regex",
                success=True,
            ))
            t0 = time.perf_counter()
            frame.imagen_prompt = await _rewrite_prompt_for_issues(prompt, regex_issues, style_constraints)
            rewrite_latency = time.perf_counter() - t0
            ledger.record(LedgerEntry(
                step_name=f"fix_prompt_frame_{frame.frame_number}",
                latency_seconds=rewrite_latency,
                estimated_cost_usd=estimate_text_cost(settings.model_fast, 600, 600),
                model=settings.model_fast,
                success=True,
            ))
        else:
            # Layer 2: LLM holistic review (cheap)
            t0 = time.perf_counter()
            passed, llm_issues, corrected = await _llm_review_prompt(prompt, style_constraints)
            review_latency = time.perf_counter() - t0
            ledger.record(LedgerEntry(
                step_name=f"review_prompt_frame_{frame.frame_number}",
                latency_seconds=review_latency,
                estimated_cost_usd=estimate_text_cost(settings.model_fast, 800, 400),
                model=settings.model_fast,
                success=True,
            ))

            if not passed:
                if corrected:
                    frame.imagen_prompt = corrected
                    logger.info("Frame {} LLM review fixed: {}", frame.frame_number, llm_issues)
                elif llm_issues:
                    # LLM found issues but didn't provide a fix — rewrite via separate call
                    t0 = time.perf_counter()
                    frame.imagen_prompt = await _rewrite_prompt_for_issues(prompt, llm_issues, style_constraints)
                    fix_latency = time.perf_counter() - t0
                    ledger.record(LedgerEntry(
                        step_name=f"fix_prompt_frame_{frame.frame_number}",
                        latency_seconds=fix_latency,
                        estimated_cost_usd=estimate_text_cost(settings.model_fast, 600, 600),
                        model=settings.model_fast,
                        success=True,
                    ))

    return storyboard


def _safe_title(title: str) -> str:
    """Convert a storyboard title into a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def enforce_runtime_target(treatment: ScriptTreatment, brief: PitchBrief) -> ScriptTreatment:
    """
    If a target runtime was specified in the brief, override the LLM's own
    estimate deterministically — no tolerance band, exact override. This
    guarantees the field is correct without trusting the LLM to honor a
    numeric instruction precisely.
    """
    if brief.target_runtime_minutes is not None:
        treatment.estimated_runtime_minutes = brief.target_runtime_minutes
    return treatment


def get_storyboard_plan(runtime_minutes: int) -> list[str]:
    """
    Returns the ordered list of narrative beats to storyboard, based on
    runtime. Frame count is len(the returned list). Max 6 frames.
    """
    if runtime_minutes <= 15:
        return ["Beginning", "Turning Point", "Ending"]
    elif runtime_minutes <= 45:
        return ["Setup", "Rising Action", "Climax", "Resolution"]
    elif runtime_minutes <= 90:
        return ["Setup", "Inciting Incident", "Midpoint", "Climax", "Resolution"]
    else:
        return ["Setup", "Inciting Incident", "Midpoint", "Dark Night of the Soul", "Climax", "Resolution"]


async def generate_storyboard_images(storyboard: Storyboard, image_style: str = "cinematic", on_stage: callable = None, job_id: str | None = None) -> Storyboard:
    """Generate images for all storyboard frames sequentially. Backoff/retry for 429s is handled in the client."""
    safe_title = _safe_title(storyboard.title)
    # Use job_id-scoped directory to prevent filename collisions across runs
    if job_id:
        output_dir = Path("outputs/storyboard") / job_id
    else:
        output_dir = Path("outputs/storyboard")
    output_dir.mkdir(parents=True, exist_ok=True)
    total_frames = len(storyboard.frames)

    def _img_stage(msg: str):
        if on_stage:
            on_stage(msg)

    # Build style constraints string based on image_style
    if image_style == "stick_figure":
        style_constraints = (
            "Zero legible text of any kind. Black and white only — no color. "
            "Stick-figure line art style — no photorealism. "
            "Background MUST be pure white — no cream, tan, grey, or any tinted background. "
            "If the background is anything other than clean white, that is a violation."
        )
    else:
        style_constraints = "No on-screen text, captions, logos, or watermarks. Cinematic photorealistic style."

    MAX_INSPECTION_RETRIES = 2

    results = []
    for frame in storyboard.frames:
        filename = f"{safe_title}_frame_{frame.frame_number:02d}.png"
        output_path = str(output_dir / filename)
        _img_stage(f"image_generation:generating:{frame.frame_number}/{total_frames}")
        logger.info(
            "Starting image generation for frame {} ...", frame.frame_number
        )
        result = await generate_frame_image(frame.imagen_prompt, output_path, style=image_style)
        if result:
            logger.success(
                "Frame {} image saved: {}", frame.frame_number, result
            )
            # Inspection loop with adaptive prompt rewriting
            current_prompt = frame.imagen_prompt
            for inspection_attempt in range(MAX_INSPECTION_RETRIES + 1):
                # Generate image (first time already done above, subsequent are retries with fixed prompt)
                if inspection_attempt > 0:
                    _img_stage(f"image_generation:retry:{frame.frame_number}/{total_frames}:{inspection_attempt}/{MAX_INSPECTION_RETRIES}")
                    logger.info("Regenerating frame {} (inspection retry {}/{}) with corrected prompt", frame.frame_number, inspection_attempt, MAX_INSPECTION_RETRIES)
                    result = await generate_frame_image(current_prompt, output_path, style=image_style)
                    if result is None:
                        break

                # Inspect
                _img_stage(f"image_generation:inspecting:{frame.frame_number}/{total_frames}")
                t0_inspect = time.perf_counter()
                inspection = await inspect_frame(result, current_prompt, style_constraints)
                inspect_latency = time.perf_counter() - t0_inspect
                ledger.record(LedgerEntry(
                    step_name=f"inspect_frame_{frame.frame_number}",
                    latency_seconds=inspect_latency,
                    estimated_cost_usd=0.005,
                    model=settings.model_fast,
                    success=True,
                ))

                if inspection.passed:
                    _img_stage(f"image_generation:passed:{frame.frame_number}/{total_frames}")
                    frame.inspection_passed = True
                    frame.inspection_issues = None
                    break
                elif inspection_attempt < MAX_INSPECTION_RETRIES:
                    # Rewrite the prompt to address the specific issues found
                    issues_text = "; ".join(inspection.issues)
                    logger.info(
                        "Frame {} failed inspection — rewriting prompt to fix: {}",
                        frame.frame_number, issues_text,
                    )
                    t0_rewrite = time.perf_counter()
                    current_prompt = await _rewrite_prompt_for_issues(
                        current_prompt, inspection.issues, style_constraints
                    )
                    rewrite_latency = time.perf_counter() - t0_rewrite
                    ledger.record(LedgerEntry(
                        step_name=f"fix_prompt_frame_{frame.frame_number}",
                        latency_seconds=rewrite_latency,
                        estimated_cost_usd=estimate_text_cost(settings.model_fast, 600, 600),
                        model=settings.model_fast,
                        success=True,
                    ))
                    logger.debug("Rewritten prompt: {}", current_prompt)
                else:
                    _img_stage(f"image_generation:failed:{frame.frame_number}/{total_frames}")
                    frame.inspection_passed = False
                    frame.inspection_issues = inspection.issues
                    logger.warning("Frame {} failed inspection after {} retries — keeping last version. Issues: {}", frame.frame_number, MAX_INSPECTION_RETRIES, inspection.issues)
        else:
            logger.warning(
                "Frame {} image generation failed", frame.frame_number
            )
        results.append((frame.frame_number, result))

    # Update frame image_path fields
    result_map = {frame_num: path for frame_num, path in results}
    for frame in storyboard.frames:
        frame.image_path = result_map.get(frame.frame_number)

    # Summary
    succeeded = sum(1 for _, path in results if path is not None)
    total = len(storyboard.frames)
    print(f"\n[Image Generation] {succeeded}/{total} frames generated successfully.")

    return storyboard


async def run_studioz_pipeline(
        brief: PitchBrief,
        screen_writer_persona: str,
        director_persona: str,
        force: bool = False,
        render_video: bool = False,
        on_stage: callable = None,
        job_id: str | None = None,
    ) -> tuple:
    """Runs the full StudioZ pipeline from pitch to storyboard"""
    logger.info("Starting StudioZ pipeline for pitch: {}...", brief.pitch[:50])
    ledger._entries = []

    def _stage(name: str):
        if on_stage:
            on_stage(name)

    try:
        _stage("screenwriter")
        print("Running Screenwriter Agent...")
        treatment = await agent_screenwriter(brief, screen_writer_persona)
        treatment = enforce_runtime_target(treatment, brief)

        _stage("grounding")
        print("Fetching Parallel Search grounding data...")
        grounding, citations = await fetch_parallel_grounding(treatment)

        _stage("committee")
        print("\nRunning Committee Review CONCURRENTLY...")
        # Build runtime-aware budget framing for the CFO
        cfo_budget_framing = (
            f"BUDGET ASSESSMENT FRAMING: This treatment's estimated_runtime_minutes is "
            f"{treatment.estimated_runtime_minutes} and the film_type is '{brief.film_type}'. "
            "When assessing budget viability, explicitly weigh these values. "
            "Do NOT default to feature-scale budget assumptions regardless of the stated runtime. "
            "Use tiered norms rather than a single bucket:\n"
            "  - Micro-short (under 5 minutes): typically well under $500K, often a few thousand "
            "to low tens-of-thousands for a lean/self-produced piece.\n"
            "  - Short (5-20 minutes): typically under $1-2M, often far less for festival-scale "
            "or indie productions.\n"
            "  - Extended short (20-40 minutes): typically $2-5M range.\n"
            "  - Feature (40+ minutes): standard feature-film budget norms apply.\n"
            "A 3-minute piece and a 35-minute piece are both 'short films' but should NOT be "
            "assessed against the same budget expectations — scale reasoning to the actual "
            "runtime within the short-film range, not just whether it clears the feature-length threshold."
        )

        # Run committee members concurrently, reporting per-member completion
        async def _run_member(persona_key, **kwargs):
            result = await agent_committee_member(treatment, persona_key, **kwargs)
            _stage(f"committee:{persona_key}_done")
            return result

        cfo_review, creative_review, legal_review = await asyncio.gather(
            _run_member(
                "cfo",
                agent_config_key="committee_member",
                grounding_context=grounding.budget_comps,
                budget_framing=cfo_budget_framing,
            ),
            _run_member(
                "creative_exec",
                agent_config_key="committee_member",
                grounding_context=grounding.market_trends,
            ),
            _run_member(
                "legal_counsel",
                agent_config_key="committee_member",
                grounding_context=grounding.ip_clearance,
            ),
        )

        # Console display for individual committee member stances
        for rev in [cfo_review, creative_review, legal_review]:
            print(f"\n[Committee Member] {rev.reviewer_name} ({rev.role})")
            print(f"Stance: {rev.stance.upper()} | Severity: {rev.severity.upper()}")
            print("Key Points:")
            for pt in rev.key_points:
                print(f" - {pt}")

        _stage("consensus")
        print("\nRunning Consensus Agent...")
        consensus_runtime_context = (
            f"NOTE: This is a {brief.film_type} film with an estimated runtime of "
            f"{treatment.estimated_runtime_minutes} minutes. The estimated_budget_millions "
            "you produce should be scaled appropriately to this runtime and film type — "
            "defer to the CFO's runtime-aware budget assessment rather than applying "
            "feature-scale assumptions independently."
        )
        exec_review = await agent_consensus(
            treatment, [cfo_review, creative_review, legal_review],
            runtime_context=consensus_runtime_context,
        )

        print(f"\n[Executive Consensus] Greenlight: {exec_review.greenlight}")
        print(f"Summary: {exec_review.summary}")

        _stage("gate")
        # Greenlight gate: skip director/image generation if not approved
        if not exec_review.greenlight and not force:
            print("\n--- PROJECT NOT GREENLIT ---")
            print("Skipping Director and image generation.")
            print("\n--- EXECUTIVE REVIEW ---")
            print(f"Summary: {exec_review.summary}")
            print(f"Budget estimate: ${exec_review.estimated_budget_millions}M")
            print(f"Target demographic: {exec_review.target_demographic}")
            print(f"Financial risks:")
            for risk in exec_review.finacial_risks:
                print(f"  - {risk}")
            print(f"Required script notes:")
            for note in exec_review.required_script_notes:
                print(f"  - {note}")
            logger.info("Pipeline stopped at greenlight gate (not approved).")
            print(ledger.summary())
            return treatment, exec_review, None, citations

        if not exec_review.greenlight and force:
            logger.warning(
                "Committee did NOT greenlight this project — proceeding to "
                "storyboard generation due to --force override."
            )

        _stage("director")
        print("Running Director Agent...")
        beats = get_storyboard_plan(treatment.estimated_runtime_minutes)
        logger.info("Storyboard plan: {} frames, beats={}", len(beats), beats)
        storyboard, image_style = await agent_director(treatment, exec_review, director_persona, beats=beats)

        # Upstream validation: rewrite prompts that contain color language (stick_figure only)
        storyboard = await validate_and_rewrite_prompts(storyboard, image_style)

        _stage("image_generation")
        print("\nRunning Image Generation for Storyboard Frames...")
        storyboard = await generate_storyboard_images(storyboard, image_style=image_style, on_stage=on_stage, job_id=job_id)

        # Persist storyboard as JSON alongside the frame images
        safe_title = _safe_title(storyboard.title)
        if job_id:
            storyboard_dir = Path("outputs/storyboard") / job_id
        else:
            storyboard_dir = OUTPUTS_DIR
        storyboard_dir.mkdir(parents=True, exist_ok=True)
        storyboard_json_path = storyboard_dir / f"{safe_title}_storyboard.json"
        storyboard_json_path.write_text(storyboard.model_dump_json(indent=2))
        logger.success("Storyboard saved: {}", storyboard_json_path)
        print(f"[Storyboard JSON] Saved to {storyboard_json_path}")

        # Video rendering (opt-in via --render-video)
        if render_video:
            # Gate: check all frames have images before spending on TTS/video
            failed_frames = [
                f.frame_number for f in storyboard.frames if f.image_path is None
            ]
            if failed_frames:
                print(f"\n[Video] Cannot proceed — {len(failed_frames)}/{len(storyboard.frames)} frames missing images.")
                print(f"  Failed frames: {failed_frames}")
                print(f"  Fix with: python -m studioz.regenerate_frame "
                      f"--storyboard {storyboard_json_path} --frame <N>")
                print(f"  Then re-run with --render-video.")
            else:
                video_path = await run_narration_pipeline(storyboard)
                if video_path:
                    print(f"\n[Video] Final output: {video_path}")
                else:
                    print("\n[Video] Video rendering failed (see logs above).")

        print("\n--- EXECUTIVE REVIEW ---")
        print(exec_review)
        print("\n--- DIRECTOR STORYBOARD ---")
        print(storyboard)

        logger.info("Pipeline completed successfully.")

        print(ledger.summary())

        return treatment, exec_review, storyboard, citations

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        print(ledger.summary())


if __name__ == "__main__":
    # Standard test pitch

    test_pitch = """
        A deep-sea mining crew discovers an alien monolith at the bottom of the Mariana Trench that begins 
        sending signals into space.
        """

    parse_args = ArgumentParser(description="Run the StudioZ pipeline with a test pitch")
    parse_args.add_argument(
        "--pitch", 
        type=str, 
        default=test_pitch,
        help="The pitch to evaluate through the StudioZ pipeline"
    )
    parse_args.add_argument(
        "--screen-writer-persona",
        type=str,
        default="blockbuster",
        choices = ["blockbuster", "indie",],
        help="Persona key for the screenwriter agent"
    )
    parse_args.add_argument(
        "--director-persona",
        type=str,
        default="high_octane",
        choices = ["high_octane", "cinematic_noir", "explainer"],
        help="Persona key for the director agent"
    )
    parse_args.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force Director/image generation even if the committee does not greenlight"
    )
    parse_args.add_argument(
        "--render-video",
        action="store_true",
        default=False,
        help="Run narration + TTS + video assembly after storyboard generation"
    )
    args = parse_args.parse_args()

    brief = PitchBrief(pitch=args.pitch)

    # Run the async pipeline using asyncio
    asyncio.run(run_studioz_pipeline(
        brief, 
        args.screen_writer_persona, 
        args.director_persona,
        force=args.force,
        render_video=args.render_video,
        )
    )
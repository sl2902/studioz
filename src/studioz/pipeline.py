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

# Color words banned in stick_figure prompts (case-insensitive regex)
_BANNED_COLOR_PATTERN = re.compile(
    r"\b(red|green|blue|orange|yellow|purple|pink|colou?r(?:ed|ful)?)\b",
    re.IGNORECASE,
)


def contains_color_language(imagen_prompt: str) -> bool:
    """Case-insensitive check for banned color words in a prompt."""
    return bool(_BANNED_COLOR_PATTERN.search(imagen_prompt))


async def _rewrite_prompt_remove_color(imagen_prompt: str) -> str:
    """
    Use a cheap text model to rewrite a prompt, removing all color references
    while preserving content and meaning. Replaces color-based status indicators
    with shape-based equivalents.
    """
    rewrite_instruction = (
        "Rewrite the following image generation prompt to remove ALL color references "
        "while preserving the same content and meaning. Replace color-based status "
        "indicators (red X, green checkmark, red warning, green light) with shape-based "
        "equivalents (plain black X shape, plain black checkmark outline, black warning "
        "triangle, black circle outline). The rewritten prompt must describe ONLY black "
        "line art on a white background. Return ONLY the rewritten prompt, nothing else."
    )
    try:
        response = await client.aio.models.generate_content(
            model=settings.model_fast,
            contents=f"{rewrite_instruction}\n\nOriginal prompt:\n{imagen_prompt}",
            config=types.GenerateContentConfig(temperature=0.1),
        )
        rewritten = response.text.strip()
        # Sanity check: if the rewrite still contains color words, fall back to regex stripping
        if contains_color_language(rewritten):
            logger.warning("Rewrite still contains color words — applying regex fallback")
            rewritten = _BANNED_COLOR_PATTERN.sub("black", rewritten)
        return rewritten
    except Exception as e:
        logger.warning("Color rewrite failed ({}), applying regex fallback", e)
        return _BANNED_COLOR_PATTERN.sub("black", imagen_prompt)


async def validate_and_rewrite_prompts(storyboard: Storyboard, image_style: str) -> Storyboard:
    """
    Upstream validation: for stick_figure-style frames, check each imagen_prompt
    for banned color words. If found, rewrite the prompt using a cheap text model
    BEFORE any image generation happens.
    """
    if image_style != "stick_figure":
        return storyboard

    for frame in storyboard.frames:
        if contains_color_language(frame.imagen_prompt):
            logger.warning(
                "Frame {} imagen_prompt contains color language — rewriting upstream",
                frame.frame_number,
            )
            logger.debug("Original prompt: {}", frame.imagen_prompt)

            t0 = time.perf_counter()
            rewritten = await _rewrite_prompt_remove_color(frame.imagen_prompt)
            latency = t0 and time.perf_counter() - t0

            # Get token usage from response if available
            cost = estimate_text_cost(settings.model_fast, 500, 500)  # Approximate
            ledger.record(LedgerEntry(
                step_name=f"color_rewrite_frame_{frame.frame_number}",
                latency_seconds=latency,
                estimated_cost_usd=cost,
                model=settings.model_fast,
                success=True,
            ))

            logger.info(
                "Frame {} prompt rewritten in {:.1f}s — color words removed",
                frame.frame_number, latency,
            )
            logger.debug("Rewritten prompt: {}", rewritten)
            frame.imagen_prompt = rewritten

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


async def generate_storyboard_images(storyboard: Storyboard, image_style: str = "cinematic") -> Storyboard:
    """Generate images for all storyboard frames sequentially. Backoff/retry for 429s is handled in the client."""
    safe_title = _safe_title(storyboard.title)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # Build style constraints string based on image_style
    if image_style == "stick_figure":
        style_constraints = "Zero legible text of any kind. Black and white only — no color. Stick-figure line art style — no photorealism."
    else:
        style_constraints = "No on-screen text, captions, logos, or watermarks. Cinematic photorealistic style."

    MAX_INSPECTION_RETRIES = 2

    results = []
    for frame in storyboard.frames:
        filename = f"{safe_title}_frame_{frame.frame_number:02d}.png"
        output_path = str(OUTPUTS_DIR / filename)
        logger.info(
            "Starting image generation for frame {} ...", frame.frame_number
        )
        result = await generate_frame_image(frame.imagen_prompt, output_path, style=image_style)
        if result:
            logger.success(
                "Frame {} image saved: {}", frame.frame_number, result
            )
            # Inspection loop
            for inspection_attempt in range(MAX_INSPECTION_RETRIES + 1):
                # Generate image (first time already done above, subsequent are retries)
                if inspection_attempt > 0:
                    logger.info("Regenerating frame {} (inspection retry {}/{})", frame.frame_number, inspection_attempt, MAX_INSPECTION_RETRIES)
                    result = await generate_frame_image(frame.imagen_prompt, output_path, style=image_style)
                    if result is None:
                        break

                # Inspect
                t0_inspect = time.perf_counter()
                inspection = await inspect_frame(result, frame.imagen_prompt, style_constraints)
                inspect_latency = time.perf_counter() - t0_inspect
                ledger.record(LedgerEntry(
                    step_name=f"inspect_frame_{frame.frame_number}",
                    latency_seconds=inspect_latency,
                    estimated_cost_usd=0.005,
                    model=settings.model_fast,
                    success=True,
                ))

                if inspection.passed:
                    break
                elif inspection_attempt == MAX_INSPECTION_RETRIES:
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
    ) -> tuple:
    """Runs the full StudioZ pipeline from pitch to storyboard"""
    logger.info("Starting StudioZ pipeline for pitch: {}...", brief.pitch[:50])
    ledger._entries = []

    try:
        print("Running Screenwriter Agent...")
        treatment = await agent_screenwriter(brief, screen_writer_persona)
        treatment = enforce_runtime_target(treatment, brief)

        print("Fetching Parallel Search grounding data...")
        grounding = await fetch_parallel_grounding(treatment)

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

        cfo_review, creative_review, legal_review = await asyncio.gather(
            agent_committee_member(
                treatment, 
                "cfo", 
                agent_config_key="committee_member", 
                grounding_context=grounding.budget_comps,
                budget_framing=cfo_budget_framing,
            ),
            agent_committee_member(
                treatment, 
                "creative_exec", 
                agent_config_key="committee_member", 
                grounding_context=grounding.market_trends
            ),
            agent_committee_member(
                treatment, 
                "legal_counsel", 
                agent_config_key="committee_member", 
                grounding_context=grounding.ip_clearance
            ),
        )

        # Console display for individual committee member stances
        for rev in [cfo_review, creative_review, legal_review]:
            print(f"\n[Committee Member] {rev.reviewer_name} ({rev.role})")
            print(f"Stance: {rev.stance.upper()} | Severity: {rev.severity.upper()}")
            print("Key Points:")
            for pt in rev.key_points:
                print(f" - {pt}")

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
            return treatment, exec_review, None

        if not exec_review.greenlight and force:
            logger.warning(
                "Committee did NOT greenlight this project — proceeding to "
                "storyboard generation due to --force override."
            )

        print("Running Director Agent...")
        beats = get_storyboard_plan(treatment.estimated_runtime_minutes)
        logger.info("Storyboard plan: {} frames, beats={}", len(beats), beats)
        storyboard, image_style = await agent_director(treatment, exec_review, director_persona, beats=beats)

        # Upstream validation: rewrite prompts that contain color language (stick_figure only)
        storyboard = await validate_and_rewrite_prompts(storyboard, image_style)

        print("\nRunning Image Generation for Storyboard Frames...")
        storyboard = await generate_storyboard_images(storyboard, image_style=image_style)

        # Persist storyboard as JSON alongside the frame images
        safe_title = _safe_title(storyboard.title)
        storyboard_json_path = OUTPUTS_DIR / f"{safe_title}_storyboard.json"
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

        return treatment, exec_review, storyboard

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
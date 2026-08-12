import asyncio
import re
from argparse import ArgumentParser
from pathlib import Path

from loguru import logger

from studioz.agents import (
    agent_committee_member,
    agent_consensus,
    agent_director,
    agent_screenwriter,
)
from studioz.clients.parallel_search import fetch_parallel_grounding
from studioz.clients.image_client import generate_frame_image
from studioz.narration_pipeline import run_narration_pipeline
from studioz.schemas import PitchBrief, ScriptTreatment, Storyboard


OUTPUTS_DIR = Path("outputs/storyboard")


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


async def generate_storyboard_images(storyboard: Storyboard) -> Storyboard:
    """Generate images for all storyboard frames sequentially. Backoff/retry for 429s is handled in the client."""
    safe_title = _safe_title(storyboard.title)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for frame in storyboard.frames:
        filename = f"{safe_title}_frame_{frame.frame_number:02d}.png"
        output_path = str(OUTPUTS_DIR / filename)
        logger.info(
            "Starting image generation for frame {} ...", frame.frame_number
        )
        result = await generate_frame_image(frame.imagen_prompt, output_path)
        if result:
            logger.success(
                "Frame {} image saved: {}", frame.frame_number, result
            )
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

    try:
        print("Running Screenwriter Agent...")
        treatment = await agent_screenwriter(brief, screen_writer_persona)
        treatment = enforce_runtime_target(treatment, brief)

        print("Fetching Parallel Search grounding data...")
        grounding = await fetch_parallel_grounding(treatment)

        print("\nRunning Committee Review CONCURRENTLY...")
        cfo_review, creative_review, legal_review = await asyncio.gather(
            agent_committee_member(
                treatment, 
                "cfo", 
                agent_config_key="committee_member", 
                grounding_context=grounding.budget_comps
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
        exec_review = await agent_consensus(
            treatment, [cfo_review, creative_review, legal_review]
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
            return treatment, exec_review, None

        if not exec_review.greenlight and force:
            logger.warning(
                "Committee did NOT greenlight this project — proceeding to "
                "storyboard generation due to --force override."
            )

        print("Running Director Agent...")
        storyboard = await agent_director(treatment, exec_review, director_persona, num_frames=brief.num_frames)

        print("\nRunning Image Generation for Storyboard Frames...")
        storyboard = await generate_storyboard_images(storyboard)

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

        return treatment, exec_review, storyboard

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")


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
        choices = ["high_octane", "cinematic_noir"],
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
    parse_args.add_argument(
        "--frames",
        type=int,
        default=3,
        help="Number of storyboard frames to generate (default: 3)"
    )
    args = parse_args.parse_args()

    brief = PitchBrief(pitch=args.pitch, num_frames=args.frames)

    # Run the async pipeline using asyncio
    asyncio.run(run_studioz_pipeline(
        brief, 
        args.screen_writer_persona, 
        args.director_persona,
        force=args.force,
        render_video=args.render_video,
        )
    )
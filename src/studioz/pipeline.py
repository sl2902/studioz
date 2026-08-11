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
from studioz.schemas import Storyboard


OUTPUTS_DIR = Path("outputs/storyboard")


def _safe_title(title: str) -> str:
    """Convert a storyboard title into a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


async def generate_storyboard_images(storyboard: Storyboard) -> Storyboard:
    """Generate images for all storyboard frames concurrently via Imagen."""
    safe_title = _safe_title(storyboard.title)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    async def _generate_for_frame(frame):
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
        return frame.frame_number, result

    results = await asyncio.gather(
        *[_generate_for_frame(frame) for frame in storyboard.frames]
    )

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
        user_pitch: str,
        screen_writer_persona: str,
        director_persona: str,
    ) -> tuple:
    """Runs the full StudioZ pipeline from pitch to storyboard"""
    logger.info("Starting StudioZ pipeline for pitch: {}...", user_pitch[:50])

    try:
        print("Running Screenwriter Agent...")
        treatment = await agent_screenwriter(user_pitch, screen_writer_persona)

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

        print("Running Director Agent...")
        storyboard = await agent_director(treatment, exec_review, director_persona)

        print("\nRunning Image Generation for Storyboard Frames...")
        storyboard = await generate_storyboard_images(storyboard)

        # Persist storyboard as JSON alongside the frame images
        safe_title = _safe_title(storyboard.title)
        storyboard_json_path = OUTPUTS_DIR / f"{safe_title}_storyboard.json"
        storyboard_json_path.write_text(storyboard.model_dump_json(indent=2))
        logger.success("Storyboard saved: {}", storyboard_json_path)
        print(f"[Storyboard JSON] Saved to {storyboard_json_path}")

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
    args = parse_args.parse_args()

    # Run the async pipeline using asyncio
    asyncio.run(run_studioz_pipeline(
        args.pitch, 
        args.screen_writer_persona, 
        args.director_persona
        )
    )
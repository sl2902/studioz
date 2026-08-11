import asyncio
from argparse import ArgumentParser
from loguru import logger

from studioz.agents import (
    agent_committee_member,
    agent_consensus,
    agent_director,
    agent_screenwriter,
)
from studioz.clients.parallel_search import fetch_parallel_grounding


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
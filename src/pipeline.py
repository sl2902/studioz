import asyncio
import os
import json
from argparse import ArgumentParser
from loguru import logger
from google import genai
from google.genai import types
from studioz.config import settings
from studioz.prompts import get_persona
from studioz.schemas import (
    MemberReview,
    ScriptTreatment,
    ExecutiveReview, 
    Storyboard, 
    StoryboardFrame,
)

# Initialize client using vertex AI using 
client = genai.Client(
    vertexai=True,
    project=settings.gcp_project,
    location=settings.gcp_location,
)

async def agent_screenwriter(pitch: str, persona_key: str = "blockbuster") -> ScriptTreatment:
    """
    Generates a script treatment using a selectable screenwriter persona
    """
    persona = get_persona("screenwriter", persona_key)
    logger.info("Screenwriter Agent active: '{}'", persona["name"])
    logger.info("Evaluating pitch via Structured Output: {}...", pitch[:50])
    
    try:
        response = await client.aio.models.generate_content(
            model=settings.model_pro,
            contents=f"Provide a script treatment for the following pitch: {pitch}",
            config=types.GenerateContentConfig(
                system_instruction=persona.get("system_instruction", ""),
                response_mime_type="application/json",
                response_schema=ScriptTreatment,
                temperature=persona.get("temperature", 0.7),
            ),
        )

        script_treatment: ScriptTreatment = response.parsed

        logger.success(
            "Successfully generated Script Treatment. Title: {}, Genre: {}",
            script_treatment.title,
            script_treatment.genre,
        )
        return script_treatment
    
    except Exception as e:
        logger.exception(f"Failed to generate structured script treatment: {e}")
        raise

async def agent_studio_head(script_treatment: ScriptTreatment, persona_key: str = "skeptical_cfo") -> ExecutiveReview:
    """Evaluates a treatment using a selectable studio head persona"""
    persona = get_persona("studio_head", persona_key)
    logger.info("Studio Head Agent active: '{}'", persona["name"])
    logger.info("Evaluating treatment via Structured Output: {}...", script_treatment.title[:50])

    system_instruction = """
    You are a cautious Studio Chief Financial Officer and Executive Producer.
    Analyze script treatments for commercial viability, budget risk, and market appeal.
    """

    try:
        response = await client.aio.models.generate_content(
            model=settings.model_pro,
            contents=f"Script Treatment:\n{script_treatment.model_dump_json()}",
            config=types.GenerateContentConfig(
                system_instruction=persona.get("system_instruction", system_instruction),
                response_mime_type="application/json",
                response_schema=ExecutiveReview,
                temperature=persona.get("temperature", 0.2),
            ),
        )
        review: ExecutiveReview = response.parsed

        logger.success(
            "Successfully generated Executive Review. Greenlight: {}, Budget: ${}M",
            review.greenlight,
            review.estimated_budget_millions,
        )
        return review

    except Exception:
        logger.exception(f"Failed to generate structured executive review")
        raise

async def agent_committee_member(
        script_treatment: ScriptTreatment, 
        persona_key: str,
        persona_group: str = "committee_member",
    ) -> MemberReview:
    """Generic committee member agent parameterized by persona group and key"""
    persona = get_persona(persona_group, persona_key)
    logger.info(
        "Committee Member '{}' ({}) reviewing script treatment...",
        persona["name"],
        persona["title"],
    )

    response = await client.aio.models.generate_content(
        model=settings.model_pro,
        contents=f"Script Treatment to Evaluate:\n{script_treatment.model_dump_json()}",
        config=types.GenerateContentConfig(
            system_instruction=persona["system_instruction"],
            response_mime_type="application/json",
            response_schema=MemberReview,
            temperature=persona.get("temperature", 0.2),
        ),
    )

    review: MemberReview = response.parsed
    logger.success(
        "Committee Member '{}' completed review with stance: '{}'",
        persona["name"],
        review.stance.upper(),
    )

    return review

async def agent_consensus(
        script_treatment: ScriptTreatment, 
        reviews: list[MemberReview],
    ) -> ExecutiveReview:
    """Synthesizes individual MemberReview feedback into a final ExecutiveReview"""
    persona = get_persona("consensus", "chair")
    logger.info("Chairperson '{}' synthesizing committee reviews...", persona["name"])

    serialized_reviews = "\n\n".join(
        f"--- REVIEWER: {r.reviewer_name} ({r.role}) ---\n{r.model_dump_json()}"
        for r in reviews
    )

    prompt = f"""
    Script Treatment:
    {script_treatment.model_dump_json()}

    Committee Member Reviews:
    {serialized_reviews}
    """

    response = await client.aio.models.generate_content(
        model=settings.model_pro,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=persona["system_instruction"],
            response_mime_type="application/json",
            response_schema=ExecutiveReview,
            temperature=persona.get("temperature", 0.3),
        ),
    )
    logger.success("Consensus synthesis complete. Greenlight: {}", response.parsed.greenlight)
    return response.parsed

async def agent_director(
        script_treatment: ScriptTreatment, 
        review: ExecutiveReview,
        persona_key: str = "high_octane",
    ) -> Storyboard:
    """Receives treatment + notes and designs visual storyboard"""
    persona = get_persona("director", persona_key)
    logger.info("Director Agent active: '{}'", persona["name"])
    logger.info("Generating storyboard via Structured Output")

    system_instruction = """
    You are a Visual Film Director.
    Create a 3-frame camera storyboard matching the approved script treatment and executive notes.
    Provide rich visual details for each camera frame prompt.
    """
    
    prompt = f"""
    Script Treatment:
    {script_treatment.model_dump_json()}

    Executive Feedback:
    Greenlit: {review.greenlight}
    Notes: {review.required_script_notes}
    """

    try:
        response = await client.aio.models.generate_content(
            model=settings.model_fast,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=persona.get("system_instruction", system_instruction),
                response_mime_type="application/json",
                response_schema=Storyboard,
                temperature=persona.get("temperature", 0.5),
            ),
        )
        storyboard: Storyboard = response.parsed

        logger.success(
            "Successfully generated Storyboard with {} frames", 
            len(storyboard.frames),
        )
        return storyboard

    except Exception as e:
        logger.exception(f"Failed to generate structured storyboard")
        raise

async def run_studioz_pipeline(
        user_pitch: str,
        screen_writer_persona: str,
        # studio_head_persona: str,
        director_persona: str
    ) -> None:
    """Runs the full StudioZ pipeline from pitch to storyboard"""
    logger.info("Starting StudioZ pipeline for pitch: {}...", user_pitch[:50])

    try:
        print("Running Screenwriter Agent...")
        treatment = await agent_screenwriter(user_pitch, screen_writer_persona)


        # print("Running Studio Head...")
        # # Executed simultaneously using asyncio.gather
        # exec_review = await agent_studio_head(treatment, studio_head_persona)

        print("\nRunning Committee Review CONCURRENTLY...")
        cfo_review, creative_review, legal_review = await asyncio.gather(
            agent_committee_member(treatment, "cfo", persona_group="committee_member"),
            agent_committee_member(treatment, "creative_exec", persona_group="committee_member"),
            agent_committee_member(treatment, "legal_counsel", persona_group="committee_member"),
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
    # parse_args.add_argument(
    #     "--studio-head-persona",
    #     type=str,
    #     default="skeptical_cfo",
    #     choices = ["skeptical_cfo", "bold_innovator"],
    #     help="Persona key for the studio head agent"
    # )
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
        # args.studio_head_persona, 
        args.director_persona
        )
    )
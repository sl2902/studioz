from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.prompts import get_persona
from studioz.schemas import MemberReview, ScriptTreatment

async def agent_committee_member(
        script_treatment: ScriptTreatment, 
        persona_key: str,
        agent_config_key: str = "committee_member",
        grounding_context: str = "No grounding data available — rely on general knowledge",
    ) -> MemberReview:
    """Executes a single committee member review with injected Parallel Search grounding context"""
    persona = get_persona(agent_config_key, persona_key)
    logger.info(
        "Committee Member '{}' ({}) reviewing script treatment...",
        persona["name"],
        persona["title"],
    )

    prompt = f"""
        Script Treatment:
        {script_treatment.model_dump_json()}

        Real-world grounding data (from Parallel Search):
        {grounding_context}

        Use the grounding data above to inform your review with real comparables where relevant. If the grounding data doesn't contain anything useful, say so explicitly in your key_points rather than inventing specifics.
        """

    response = await client.aio.models.generate_content(
        model=settings.model_pro,
        contents=prompt,
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

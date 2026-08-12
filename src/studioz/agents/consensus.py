from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.prompts import get_persona
from studioz.schemas import ExecutiveReview, MemberReview, ScriptTreatment

async def agent_consensus(
        script_treatment: ScriptTreatment, 
        reviews: list[MemberReview],
        runtime_context: str = "",
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

    if runtime_context:
        prompt += f"\n\n{runtime_context}"

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

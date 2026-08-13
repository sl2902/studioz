import time

from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.ledger import ledger, LedgerEntry, estimate_text_cost
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

    t0 = time.perf_counter()
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
    latency = time.perf_counter() - t0
    usage = getattr(response, 'usage_metadata', None)
    input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
    output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0
    cost = estimate_text_cost(settings.model_pro, input_tokens, output_tokens)
    ledger.record(LedgerEntry(
        step_name="consensus",
        latency_seconds=latency,
        estimated_cost_usd=cost,
        model=settings.model_pro,
        success=True,
    ))
    logger.info("consensus completed in {:.1f}s (est. ${:.4f})", latency, cost)
    return response.parsed

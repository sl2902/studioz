import time

from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.ledger import ledger, LedgerEntry, estimate_text_cost
from studioz.prompts import get_persona
from studioz.schemas import MemberReview, ScriptTreatment

async def agent_committee_member(
        script_treatment: ScriptTreatment, 
        persona_key: str,
        agent_config_key: str = "committee_member",
        grounding_context: str = "No grounding data available — rely on general knowledge",
        budget_framing: str = "",
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

    if budget_framing:
        prompt += f"\n\n{budget_framing}"

    t0 = time.perf_counter()
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
    latency = time.perf_counter() - t0
    usage = getattr(response, 'usage_metadata', None)
    input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
    output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0
    cost = estimate_text_cost(settings.model_pro, input_tokens, output_tokens)
    ledger.record(LedgerEntry(
        step_name=f"committee_{persona_key}",
        latency_seconds=latency,
        estimated_cost_usd=cost,
        model=settings.model_pro,
        success=True,
    ))
    logger.info("committee_{} completed in {:.1f}s (est. ${:.4f})", persona_key, latency, cost)
    logger.success(
        "Committee Member '{}' completed review with stance: '{}'",
        persona["name"],
        review.stance.upper(),
    )

    return review

import time

from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.ledger import ledger, LedgerEntry, estimate_text_cost
from studioz.prompts import get_persona
from studioz.schemas import PitchBrief, ScriptTreatment

async def agent_screenwriter(brief: PitchBrief, persona_key: str = "blockbuster") -> ScriptTreatment:
    """
    Generates a script treatment using a selectable screenwriter persona.
    Accepts a PitchBrief which may include film_type and target_runtime constraints.
    """
    persona = get_persona("screenwriter", persona_key)
    logger.info("Screenwriter Agent active: '{}'", persona["name"])
    logger.info("Evaluating pitch via Structured Output: {}...", brief.pitch[:50])

    # Build constraint text for the prompt
    constraints = f"This must be a {brief.film_type} film."
    if brief.target_runtime_minutes is not None:
        constraints += (
            f" The target runtime is approximately {brief.target_runtime_minutes} minutes."
            " Pace the story, synopsis, and scene content appropriately for this length."
        )

    prompt = (
        f"Provide a script treatment for the following pitch: {brief.pitch}\n\n"
        f"Constraints: {constraints}"
    )
    
    try:
        t0 = time.perf_counter()
        response = await client.aio.models.generate_content(
            model=settings.model_pro,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=persona.get("system_instruction", ""),
                response_mime_type="application/json",
                response_schema=ScriptTreatment,
                temperature=persona.get("temperature", 0.7),
            ),
        )

        script_treatment: ScriptTreatment = response.parsed

        latency = time.perf_counter() - t0
        usage = getattr(response, 'usage_metadata', None)
        input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
        output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0
        cost = estimate_text_cost(settings.model_pro, input_tokens, output_tokens)
        ledger.record(LedgerEntry(
            step_name="screenwriter",
            latency_seconds=latency,
            estimated_cost_usd=cost,
            model=settings.model_pro,
            success=True,
        ))
        logger.info("screenwriter completed in {:.1f}s (est. ${:.4f})", latency, cost)

        logger.success(
            "Successfully generated Script Treatment. Title: {}, Genre: {}",
            script_treatment.title,
            script_treatment.genre,
        )
        return script_treatment
    
    except Exception as e:
        latency = time.perf_counter() - t0
        ledger.record(LedgerEntry(
            step_name="screenwriter",
            latency_seconds=latency,
            estimated_cost_usd=0.0,
            model=settings.model_pro,
            success=False,
        ))
        logger.exception(f"Failed to generate structured script treatment: {e}")
        raise

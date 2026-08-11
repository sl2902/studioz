from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.prompts import get_persona
from studioz.schemas import ScriptTreatment

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

from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.prompts import get_persona
from studioz.schemas import ExecutiveReview, ScriptTreatment, Storyboard

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

    CRITICAL RULES for the imagen_prompt field:
    - Describe your directorial style using ONLY visual language: camera angles,
      lens choices, lighting setups, color palettes, movement, composition.
    - NEVER include your persona name or any director/cinematographer name as
      literal text in the imagen_prompt. The image model will render names as
      on-screen text captions if included.
    - Do NOT include any text overlays, captions, titles, HUD elements, logos,
      or watermarks in your image descriptions.
    - Each imagen_prompt should describe a pure visual scene — what the camera
      sees — with no text or UI elements of any kind.
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

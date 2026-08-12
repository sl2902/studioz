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
        num_frames: int = 3,
    ) -> Storyboard:
    """Receives treatment + notes and designs visual storyboard"""
    persona = get_persona("director", persona_key)
    logger.info("Director Agent active: '{}'", persona["name"])
    logger.info("Generating {}-frame storyboard via Structured Output", num_frames)

    system_instruction = f"""
    You are a Visual Film Director.
    Create EXACTLY {num_frames} frames for the camera storyboard matching the approved script treatment and executive notes.
    You MUST produce exactly {num_frames} StoryboardFrame entries — no more, no fewer.
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

    # Combine the frame-count/rules instruction with the persona's style instruction
    persona_style = persona.get("system_instruction", "")
    combined_instruction = system_instruction + "\n" + persona_style
    
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
                system_instruction=combined_instruction,
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

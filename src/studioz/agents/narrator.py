from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.schemas import NarrationScript, Storyboard


async def agent_narrator(storyboard: Storyboard) -> NarrationScript:
    """
    Generates a narration script for the entire storyboard in one LLM call.
    Produces natural, spoken documentary/trailer-style narration derived from
    each frame's scene_description — tightened and narratable, not verbatim.
    """
    logger.info("Narrator Agent active: generating narration for '{}'", storyboard.title)

    system_instruction = """
    You are a professional documentary/trailer narrator writer.
    Given a storyboard with multiple frames, write a narration script with one
    segment per frame. Each segment should be:
    - Natural spoken language suitable for voiceover (1-2 sentences)
    - Derived from the frame's scene_description but tightened into evocative,
      narratable prose — NOT a verbatim readout of the description
    - Written to flow naturally from one segment to the next as continuous speech
    - Dramatic and engaging, in the style of a film trailer or nature documentary
    
    Return exactly one NarrationSegment per frame, in frame order.
    """

    frames_text = "\n".join(
        f"Frame {f.frame_number}: {f.scene_description}"
        for f in storyboard.frames
    )

    prompt = f"""
    Storyboard Title: {storyboard.title}
    
    Frames:
    {frames_text}
    """

    try:
        response = await client.aio.models.generate_content(
            model=settings.model_fast,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=NarrationScript,
                temperature=0.6,
            ),
        )

        narration: NarrationScript = response.parsed
        logger.success(
            "Narration script generated: {} segments for '{}'",
            len(narration.segments),
            narration.title,
        )
        return narration

    except Exception as e:
        logger.exception(f"Failed to generate narration script: {e}")
        raise

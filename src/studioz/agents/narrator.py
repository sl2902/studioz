import time

from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.ledger import ledger, LedgerEntry, estimate_text_cost
from studioz.schemas import NarrationScript, Storyboard


async def agent_narrator(storyboard: Storyboard) -> NarrationScript:
    """
    Generates a hybrid table-read narration script for the storyboard:
    Narrator scene-setup + optional single-character dialogue per frame,
    with inline Gemini TTS audio tags for expressive delivery.
    """
    logger.info("Narrator Agent active: generating narration for '{}'", storyboard.title)

    system_instruction = """
    You are a professional film narrator/table-read director.
    Given a storyboard with multiple frames, write a narration script in hybrid
    "table read" format. For each frame, produce:

    1. narrator_text: Third-person scene-setup narration (1-2 sentences).
       - Set the mood, describe the action, establish atmosphere.
       - Use inline Gemini TTS audio tags for expressive delivery:
         [tense], [whispering], [low voice], [excited], [somber],
         [short pause], [long pause], etc.
       - Tags must NOT be placed directly adjacent to each other — always
         have actual text between tags.
       - Keep it evocative and dramatic, not a flat description.

    2. dialogue (optional): If the frame's scene_description mentions or implies
       a character speaking, include ONE character's direct speech line.
       - character_name MUST match a character already described or implied in
         that frame's scene_description. Do NOT invent new characters.
       - character_gender: Infer from context already present in the scene
         (pronouns like he/she/they, gendered names, gendered roles like
         "captain", "her crew", etc.). Use "male" or "female" when the context
         is clear. Use "neutral" ONLY when genuinely ambiguous or unspecified —
         do not default everything to neutral as a lazy fallback.
       - The line should use audio tags for delivery style:
         e.g. "[shouting] We're dropping too fast!"
         e.g. "[whispering, tense] Something is down here with us."
       - AT MOST one character speaks per frame. If no dialogue fits
         naturally, set dialogue to null.

    RULES:
    - Return exactly one NarrationSegment per frame, in frame order.
    - Audio tags are square-bracket modifiers: [whispers], [shouting],
      [laughs], [short pause], [long pause], [tense], [excited], etc.
    - Never place two tags adjacent without text between them.
    - The narration should flow naturally from frame to frame as if
      reading a movie aloud to an audience.
    - GREENLIGHT TERMINOLOGY: If the story involves a fictional pitch being
      approved/rejected within its own plot, avoid using the exact words
      "greenlit", "greenlight", or "the committee approved" — these are
      real-world StudioZ system terms that could be confused with the
      actual committee's real verdict. Instead use alternatives like
      "the idea moved forward", "found its way to production",
      "was given the go-ahead", etc.
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
        t0 = time.perf_counter()
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
        latency = time.perf_counter() - t0
        usage = getattr(response, 'usage_metadata', None)
        input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
        output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0
        cost = estimate_text_cost(settings.model_fast, input_tokens, output_tokens)
        ledger.record(LedgerEntry(
            step_name="narrator",
            latency_seconds=latency,
            estimated_cost_usd=cost,
            model=settings.model_fast,
            success=True,
        ))
        logger.info("narrator completed in {:.1f}s (est. ${:.4f})", latency, cost)

        logger.success(
            "Narration script generated: {} segments for '{}'",
            len(narration.segments),
            narration.title,
        )
        return narration

    except Exception as e:
        latency = time.perf_counter() - t0
        ledger.record(LedgerEntry(
            step_name="narrator",
            latency_seconds=latency,
            estimated_cost_usd=0.0,
            model=settings.model_fast,
            success=False,
        ))
        logger.exception(f"Failed to generate narration script: {e}")
        raise

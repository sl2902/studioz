import time

from loguru import logger
from google.genai import types
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.ledger import ledger, LedgerEntry, estimate_text_cost
from studioz.prompts import get_persona
from studioz.schemas import ExecutiveReview, ScriptTreatment, Storyboard

async def agent_director(
        script_treatment: ScriptTreatment, 
        review: ExecutiveReview,
        persona_key: str = "high_octane",
        beats: list[str] | None = None,
    ) -> tuple[Storyboard, str]:
    """Receives treatment + notes and designs visual storyboard.
    
    Returns:
        A tuple of (Storyboard, image_style) where image_style is read from
        the selected persona's config (e.g. "cinematic", "stick_figure").
    """
    if beats is None:
        beats = ["Beginning", "Turning Point", "Ending"]

    num_frames = len(beats)
    persona = get_persona("director", persona_key)
    image_style = persona.get("image_style", "cinematic")
    logger.info("Director Agent active: '{}' (image_style={})", persona["name"], image_style)
    logger.info("Generating {}-frame storyboard via Structured Output", num_frames)

    # Build the beat assignment text for the prompt
    beat_assignments = "\n".join(
        f"    - Frame {i+1}: {beat}" for i, beat in enumerate(beats)
    )

    system_instruction = f"""
    You are a Visual Film Director.
    Create EXACTLY {num_frames} frames for the camera storyboard matching the approved script treatment and executive notes.
    You MUST produce exactly {num_frames} StoryboardFrame entries — no more, no fewer.

    Each frame corresponds to a specific narrative beat. Assign each frame's
    content to match its designated beat:
{beat_assignments}

    Each frame's scene_description and imagen_prompt MUST reflect its assigned
    narrative beat — e.g. the "Climax" frame should depict the story's most
    intense/pivotal moment, "Setup" should establish the world/characters, etc.
    Set each frame's narrative_beat field to its assigned beat label.

    DIALOGUE/STAGING RULE:
    - Each frame may feature AT MOST ONE character with spoken dialogue.
    - If a scene naturally involves multiple speaking characters, split their
      lines across separate frames (one character's line per frame).
    - If additional characters must be present in a frame, fold their words into
      the scene_description as reported/ambient speech rather than direct dialogue
      (e.g. "In the background, the sonar technician calls out a warning").

    CRITICAL RULES for the imagen_prompt field:
    - Describe your directorial style using ONLY visual language: camera angles,
      lens choices, lighting setups, color palettes, movement, composition.
    - NEVER include your persona name or any director/cinematographer name as
      literal text in the imagen_prompt. The image model will render names as
      on-screen text captions if included.
    - NEVER include character names in the imagen_prompt — not in parentheses,
      not as labels, not as identifiers. Do NOT write things like "(REMI)" or
      "(B.A.R.R.Y.)" — describe figures only by their visual attributes (e.g.
      "a stick figure with a quill icon above its head"). Any text-like content
      in the prompt will be rendered as visible on-screen text by the image model.
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
        t0 = time.perf_counter()
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

        latency = time.perf_counter() - t0
        usage = getattr(response, 'usage_metadata', None)
        input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
        output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0
        cost = estimate_text_cost(settings.model_fast, input_tokens, output_tokens)
        ledger.record(LedgerEntry(
            step_name="director",
            latency_seconds=latency,
            estimated_cost_usd=cost,
            model=settings.model_fast,
            success=True,
        ))
        logger.info("director completed in {:.1f}s (est. ${:.4f})", latency, cost)

        logger.success(
            "Successfully generated Storyboard with {} frames", 
            len(storyboard.frames),
        )
        return storyboard, image_style

    except Exception as e:
        latency = time.perf_counter() - t0
        ledger.record(LedgerEntry(
            step_name="director",
            latency_seconds=latency,
            estimated_cost_usd=0.0,
            model=settings.model_fast,
            success=False,
        ))
        logger.exception(f"Failed to generate structured storyboard")
        raise

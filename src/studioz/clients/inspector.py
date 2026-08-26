"""Frame inspection: cheap vision call to verify generated images match constraints."""

import base64

from google.genai import types
from loguru import logger

from studioz.clients.storage import storage
from studioz.clients.vertex_client import client
from studioz.config import settings
from studioz.schemas import FrameInspectionResult

# Use the cheap/fast model for inspection — this is vision reasoning, not generation
INSPECTOR_MODEL = settings.model_fast


async def inspect_frame(
    image_path: str,
    imagen_prompt: str,
    style_constraints: str,
) -> FrameInspectionResult:
    """
    Inspect a generated frame image against its intended prompt and style constraints.
    Uses a cheap vision model to check for constraint violations.
    
    Args:
        image_path: Path to the generated image file (local path or blob path).
        imagen_prompt: The original prompt used to generate the image.
        style_constraints: Style-specific constraints to check (e.g. "zero legible text").
    
    Returns:
        FrameInspectionResult with passed=True if OK, or issues list if problems found.
    """
    # Normalize to blob path (strip outputs/ prefix if present)
    blob_path = image_path
    if blob_path.startswith("outputs/"):
        blob_path = blob_path[len("outputs/"):]

    image_bytes = await storage.read_file(blob_path)
    if image_bytes is None:
        logger.warning("Frame inspection: could not read image at '{}' — treating as pass", blob_path)
        return FrameInspectionResult(passed=True, issues=[])

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    inspection_prompt = f"""You are a quality inspector for generated storyboard images. Your job is to catch HARD violations that make a frame unusable — not to nitpick minor compositional details.

HARD RULES (set passed=false and list in "issues" if ANY of these are violated):
- ZERO TEXT: Any legible text, labels, captions, watermarks, letters, or words anywhere in the image. Even partially legible characters count.
- STYLE/COLOR: The image must satisfy these style constraints exactly:
  {style_constraints}
  For monochrome/stick-figure styles: any color (other than black lines on white/near-white background) is a hard fail. For cinematic styles: dramatically wrong color palette (e.g. black-and-white when color was requested) is a hard fail.

MINOR (record in "minor_notes" but do NOT set passed=false for these):
- Slight background tone variation (off-white, cream, light gray vs. pure white) — only fail if it's a dramatically wrong color, not a subtle tint.
- Object count mismatches in background details (two similar shapes instead of one, extra small elements).
- Imprecise icon/symbol geometry (e.g. "target" vs. "viewfinder" icon shape) — as long as a reasonable distinguishing icon is present near the correct figure.
- Minor object shape deviations (e.g. "cube" vs. "rectangular block") that don't change what the object represents.
- Line-origin points or exact spatial arrangement of decorative background elements.
- Scene composition being slightly different from the prompt while still depicting the same overall scene and mood.

The intended scene (for reference, not strict pixel-matching):
"{imagen_prompt}"

DECISION RULE:
- passed=true if there is NO legible text AND the color/style hard constraints are met. Minor compositional differences are acceptable.
- passed=false ONLY for text or color/style violations. Put these in "issues".
- Put any minor observations in "minor_notes" (these are informational only and will NOT trigger a retry)."""

    try:
        response = await client.aio.models.generate_content(
            model=INSPECTOR_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=inspection_prompt),
                        types.Part(inline_data=types.Blob(data=image_bytes, mime_type="image/png")),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FrameInspectionResult,
                temperature=0.1,
            ),
        )
        result: FrameInspectionResult = response.parsed
        if result.passed:
            logger.info("Frame inspection PASSED: {}", image_path)
            if result.minor_notes:
                logger.debug("Frame inspection minor notes for {}: {}", image_path, result.minor_notes)
        else:
            logger.warning("Frame inspection FAILED: {} — issues: {}", image_path, result.issues)
        return result

    except Exception as e:
        logger.warning("Frame inspection error (treating as pass): {}", e)
        # On inspection failure, don't block the pipeline — treat as pass
        return FrameInspectionResult(passed=True, issues=[])

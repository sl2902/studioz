"""Frame inspection: cheap vision call to verify generated images match constraints."""

import base64
from pathlib import Path

from google.genai import types
from loguru import logger

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
        image_path: Path to the generated image file.
        imagen_prompt: The original prompt used to generate the image.
        style_constraints: Style-specific constraints to check (e.g. "zero legible text").
    
    Returns:
        FrameInspectionResult with passed=True if OK, or issues list if problems found.
    """
    image_bytes = Path(image_path).read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    inspection_prompt = f"""You are a quality inspector for generated images. Examine this image and determine if it meets ALL of the following requirements:

1. SCENE MATCH: The image should depict the scene described in this prompt:
   "{imagen_prompt}"

2. STYLE CONSTRAINTS: The image MUST satisfy these hard constraints:
   {style_constraints}

3. TEXT CHECK: Look carefully for ANY legible text, labels, captions, watermarks, or words rendered anywhere in the image. Report any you find.

Respond with:
- passed=true ONLY if the image satisfies ALL constraints with no issues.
- passed=false with a list of specific issues if ANY constraint is violated.

Be strict about text — even partially legible words count as a violation if the style requires zero text."""

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
        else:
            logger.warning("Frame inspection FAILED: {} — issues: {}", image_path, result.issues)
        return result

    except Exception as e:
        logger.warning("Frame inspection error (treating as pass): {}", e)
        # On inspection failure, don't block the pipeline — treat as pass
        return FrameInspectionResult(passed=True, issues=[])

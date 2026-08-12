from pathlib import Path

from google.genai import types
from loguru import logger

from studioz.clients.vertex_client import client

IMAGE_MODEL = "gemini-2.5-flash-image"

# Fixed suffix appended to every image prompt to prevent the model from
# rendering unwanted text, captions, logos, or UI overlays into the image.
_NO_TEXT_SUFFIX = " Render as a pure photograph with no text or graphics overlaid."


async def generate_frame_image(imagen_prompt: str, output_path: str) -> str | None:
    """
    Generates an image for the given prompt via Vertex AI (gemini-2.5-flash-image),
    saves it to output_path, and returns the path.

    Uses image_config with aspect_ratio="16:9" for proper cinematic framing
    (produces 1376x768 images with no letterboxing or cropping).

    Returns None (instead of raising) if generation fails for any reason
    (quota, content filter, network error, etc.).
    """
    try:
        logger.info(
            "Generating image for prompt: '{}...' -> {}",
            imagen_prompt[:60],
            output_path,
        )

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        response = await client.aio.models.generate_content(
            model=IMAGE_MODEL,
            contents=imagen_prompt + _NO_TEXT_SUFFIX,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="16:9"),
            ),
        )

        # Extract image data from response parts
        if not response.candidates:
            # Log why the response was empty — usually a safety filter
            block_reason = getattr(response, "prompt_feedback", None)
            logger.warning(
                "Image generation failed for '{}': no candidates returned. "
                "prompt_feedback={}", output_path, block_reason
            )
            return None

        # Check if the candidate was blocked by finish_reason
        candidate = response.candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason and str(finish_reason) not in ("STOP", "0", "FinishReason.STOP"):
            logger.warning(
                "Image generation failed for '{}': finish_reason={}",
                output_path, finish_reason
            )
            return None

        image_bytes = None
        for part in candidate.content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                image_bytes = part.inline_data.data
                break

        if image_bytes is None:
            logger.warning(
                "Image generation failed for '{}': no image data in response parts",
                output_path,
            )
            return None

        # Write raw image bytes to disk
        Path(output_path).write_bytes(image_bytes)
        logger.success("Image saved: {}", output_path)
        return output_path

    except Exception as e:
        logger.warning("Image generation failed for '{}': {}", output_path, e)
        return None

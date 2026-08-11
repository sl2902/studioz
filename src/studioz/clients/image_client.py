import warnings
from pathlib import Path

from google.genai import types
from loguru import logger

from studioz.clients.vertex_client import client

# imagen-4.0-generate-001 via generate_images is deprecated (shutdown Aug 2026).
# TODO: Migrate to Interactions API with gemini-3.1-flash-image once available
# on Vertex AI. See https://ai.google.dev/gemini-api/docs/deprecations#imagen-models
IMAGEN_MODEL = "imagen-4.0-generate-001"

# Suppress the ExperimentalWarning from the SDK about generate_images deprecation
warnings.filterwarnings("ignore", message=".*generate_images.*deprecated.*")


async def generate_frame_image(imagen_prompt: str, output_path: str) -> str | None:
    """
    Generates an image for the given prompt via Vertex AI Imagen
    (imagen-4.0-generate-001), saves it to output_path, and returns the path.

    Uses aspect_ratio="16:9" for cinematic framing. Generates a single image
    per call (number_of_images=1).

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

        response = await client.aio.models.generate_images(
            model=IMAGEN_MODEL,
            prompt=imagen_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
                output_mime_type="image/png",
            ),
        )

        # Check if any images were actually generated (may be filtered)
        if not response.generated_images:
            reason = "No images returned (likely filtered by safety/RAI policy)"
            logger.warning("Image generation failed for '{}': {}", output_path, reason)
            return None

        generated = response.generated_images[0]

        # Check if this specific image was filtered
        if generated.rai_filtered_reason:
            logger.warning(
                "Image filtered for '{}': {}",
                output_path,
                generated.rai_filtered_reason,
            )
            return None

        generated.image.save(output_path)
        logger.success("Image saved: {}", output_path)
        return output_path

    except Exception as e:
        logger.warning("Image generation failed for '{}': {}", output_path, e)
        return None

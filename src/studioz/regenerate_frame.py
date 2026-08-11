"""
Standalone script to regenerate a single storyboard frame's image.

Usage:
    python -m studioz.regenerate_frame \
        --storyboard outputs/storyboard/abyssal_echo_storyboard.json \
        --frame 2 \
        [--prompt "New prompt text to override the existing imagen_prompt"]

This reloads a previously saved storyboard JSON, regenerates the image for
one specific frame (optionally with a new prompt), updates the JSON on disk,
and leaves all other frames untouched.
"""

import asyncio
import sys
from argparse import ArgumentParser
from pathlib import Path

from studioz.clients.image_client import generate_frame_image
from studioz.pipeline import _safe_title, OUTPUTS_DIR
from studioz.schemas import Storyboard


def _load_storyboard(path: Path) -> Storyboard:
    """Load and validate a storyboard JSON file."""
    if not path.exists():
        print(f"Error: Storyboard file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        return Storyboard.model_validate_json(path.read_text())
    except Exception as e:
        print(f"Error: Failed to parse storyboard JSON: {e}", file=sys.stderr)
        sys.exit(1)


def _find_frame(storyboard: Storyboard, frame_number: int):
    """Find a frame by number, exit with a clear error if out of range."""
    for frame in storyboard.frames:
        if frame.frame_number == frame_number:
            return frame

    valid_numbers = sorted(f.frame_number for f in storyboard.frames)
    print(
        f"Error: Frame {frame_number} not found in storyboard. "
        f"Available frame numbers: {valid_numbers}",
        file=sys.stderr,
    )
    sys.exit(1)


async def regenerate_frame(
    storyboard_path: Path,
    frame_number: int,
    prompt_override: str | None = None,
) -> None:
    """Regenerate a single frame's image and update the storyboard JSON."""
    storyboard = _load_storyboard(storyboard_path)
    frame = _find_frame(storyboard, frame_number)

    # Apply prompt override if provided
    prompt_was_overridden = False
    if prompt_override is not None:
        frame.imagen_prompt = prompt_override
        prompt_was_overridden = True

    # Determine output path using the same naming convention as the pipeline
    safe_title = _safe_title(storyboard.title)
    filename = f"{safe_title}_frame_{frame.frame_number:02d}.png"
    output_path = str(OUTPUTS_DIR / filename)

    # Generate the image
    print(f"Regenerating frame {frame_number}...")
    if prompt_was_overridden:
        print(f"  Prompt overridden: '{frame.imagen_prompt[:80]}...'")
    else:
        print(f"  Using existing prompt: '{frame.imagen_prompt[:80]}...'")

    result = await generate_frame_image(frame.imagen_prompt, output_path)

    # Update the frame's image_path
    frame.image_path = result

    # Save the updated storyboard back to the same JSON file
    storyboard_path.write_text(storyboard.model_dump_json(indent=2))

    # Print confirmation
    print()
    if result:
        print(f"✓ Frame {frame_number} regenerated successfully.")
        print(f"  Image path: {result}")
    else:
        print(f"✗ Frame {frame_number} image generation failed (image_path set to null).")

    if prompt_was_overridden:
        print(f"  Prompt was overridden (updated in storyboard JSON).")
    else:
        print(f"  Prompt unchanged (reused existing).")

    print(f"  Storyboard JSON updated: {storyboard_path}")


def main():
    parser = ArgumentParser(
        description="Regenerate a single storyboard frame's image without re-running the full pipeline."
    )
    parser.add_argument(
        "--storyboard",
        type=Path,
        required=True,
        help="Path to the storyboard JSON file (e.g. outputs/storyboard/my_film_storyboard.json)",
    )
    parser.add_argument(
        "--frame",
        type=int,
        required=True,
        help="Frame number to regenerate",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Optional new imagen_prompt to use instead of the existing one",
    )
    args = parser.parse_args()

    asyncio.run(regenerate_frame(args.storyboard, args.frame, args.prompt))


if __name__ == "__main__":
    main()

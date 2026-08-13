"""
Render video from an existing storyboard JSON file.

Skips screenwriter, committee, consensus, director, and image generation —
goes straight to narration → TTS → video assembly using the storyboard
that's already been generated and has images on disk.

Usage:
    python -m studioz.render_video --storyboard outputs/storyboard/silicon_slate_storyboard.json
"""

import asyncio
from argparse import ArgumentParser
from pathlib import Path

from loguru import logger

from studioz.narration_pipeline import run_narration_pipeline
from studioz.schemas import Storyboard


def main():
    parser = ArgumentParser(
        description="Render narrated video from an existing storyboard JSON"
    )
    parser.add_argument(
        "--storyboard",
        type=str,
        required=True,
        help="Path to the storyboard JSON file (e.g. outputs/storyboard/xyz_storyboard.json)",
    )
    args = parser.parse_args()

    storyboard_path = Path(args.storyboard)
    if not storyboard_path.exists():
        logger.error("Storyboard file not found: {}", storyboard_path)
        return

    # Load storyboard from JSON
    storyboard = Storyboard.model_validate_json(storyboard_path.read_text())
    print(f"[Storyboard] Loaded '{storyboard.title}' ({len(storyboard.frames)} frames)")

    # Check all frames have images
    missing = [f.frame_number for f in storyboard.frames if not f.image_path or not Path(f.image_path).exists()]
    if missing:
        logger.error(
            "Cannot render video — {} frame(s) missing images: {}",
            len(missing), missing,
        )
        print(f"Missing images for frames: {missing}")
        print("Run the full pipeline or use regenerate_frame to fix these first.")
        return

    print(f"[Storyboard] All {len(storyboard.frames)} frames have images on disk.")
    print("Starting narration → TTS → video assembly...\n")

    video_path = asyncio.run(run_narration_pipeline(storyboard))
    if video_path:
        print(f"\n[Done] Video saved: {video_path}")
    else:
        print("\n[Failed] Video rendering failed (see logs above).")


if __name__ == "__main__":
    main()

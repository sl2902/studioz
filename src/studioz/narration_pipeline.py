"""
Narration pipeline: orchestrates narrator agent -> TTS -> timeline -> video assembly.
Called from pipeline.py when --render-video is set.
"""

import re
from pathlib import Path

from loguru import logger

from studioz.agents.narrator import agent_narrator
from studioz.clients.tts_client import generate_narration_audio
from studioz.clients.video_builder import build_video, get_audio_duration
from studioz.schemas import NarrationScript, Storyboard


VIDEO_OUTPUTS_DIR = Path("outputs/video")


def _safe_title(title: str) -> str:
    """Convert a title into a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def _calculate_frame_durations(
    narration: NarrationScript, total_audio_duration: float
) -> list[float]:
    """
    Compute per-frame durations proportional to narration text length,
    normalized so they sum exactly to total_audio_duration.
    """
    # Use word count as the proxy for relative duration
    word_counts = [len(seg.narration_text.split()) for seg in narration.segments]
    total_words = sum(word_counts)

    if total_words == 0:
        # Fallback: equal split
        n = len(narration.segments)
        return [total_audio_duration / n] * n

    # Scale each segment's duration proportionally
    durations = [
        (wc / total_words) * total_audio_duration for wc in word_counts
    ]

    # Enforce minimum 1.5s per frame to avoid flicker
    min_duration = 1.5
    for i in range(len(durations)):
        if durations[i] < min_duration:
            durations[i] = min_duration

    # Re-normalize to sum exactly to total_audio_duration
    current_sum = sum(durations)
    scale = total_audio_duration / current_sum
    durations = [d * scale for d in durations]

    return durations


async def run_narration_pipeline(storyboard: Storyboard) -> str | None:
    """
    Full narration-to-video pipeline:
    1. Generate narration script from storyboard
    2. Generate TTS audio from narration
    3. Measure audio duration
    4. Build per-frame timeline
    5. Assemble final video

    Returns path to the final .mp4 on success, None on failure.
    """
    safe_title = _safe_title(storyboard.title)

    # Step 1: Generate narration script
    print("\nRunning Narrator Agent...")
    narration = await agent_narrator(storyboard)

    print(f"\n[Narration Script] {len(narration.segments)} segments:")
    for seg in narration.segments:
        print(f"  Frame {seg.frame_number}: {seg.narration_text}")

    # Step 2: Generate TTS audio (single continuous file)
    full_narration_text = " ".join(seg.narration_text for seg in narration.segments)
    audio_dir = Path("outputs/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(audio_dir / f"{safe_title}_narration.wav")

    print("\nGenerating narration audio via TTS...")
    result = await generate_narration_audio(full_narration_text, audio_path)
    if result is None:
        logger.error("TTS generation failed — cannot assemble video")
        print("[Video] TTS generation failed. Skipping video assembly.")
        return None

    # Step 3: Measure audio duration
    total_duration = await get_audio_duration(audio_path)
    if total_duration is None:
        logger.error("Could not measure audio duration — cannot assemble video")
        print("[Video] Could not measure audio duration. Skipping video assembly.")
        return None

    print(f"[Audio] Duration: {total_duration:.2f}s")

    # Step 4: Build per-frame timeline
    durations = _calculate_frame_durations(narration, total_duration)
    print(f"\n[Timeline] Per-frame durations (total={sum(durations):.2f}s):")
    for seg, dur in zip(narration.segments, durations):
        print(f"  Frame {seg.frame_number}: {dur:.2f}s")

    # Step 5: Assemble video
    # Collect frame image paths (only frames that have images)
    frame_image_paths = []
    frame_durations = []
    for i, frame in enumerate(storyboard.frames):
        if frame.image_path and Path(frame.image_path).exists():
            frame_image_paths.append(frame.image_path)
            frame_durations.append(durations[i])
        else:
            logger.warning(
                "Frame {} has no image (skipping in video): {}",
                frame.frame_number, frame.image_path
            )

    if not frame_image_paths:
        logger.error("No frame images available — cannot assemble video")
        print("[Video] No frame images available. Skipping video assembly.")
        return None

    # Re-normalize durations if we dropped frames
    if len(frame_durations) < len(durations):
        current_sum = sum(frame_durations)
        scale = total_duration / current_sum
        frame_durations = [d * scale for d in frame_durations]

    VIDEO_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    video_path = str(VIDEO_OUTPUTS_DIR / f"{safe_title}.mp4")

    print("\nAssembling video...")
    result = await build_video(frame_image_paths, frame_durations, audio_path, video_path)
    if result is None:
        print("[Video] Assembly failed.")
        return None

    print(f"[Video] Final video saved: {video_path}")
    return video_path

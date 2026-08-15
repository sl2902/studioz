"""
Narration pipeline: orchestrates narrator agent -> TTS -> timeline -> video assembly.
Called from pipeline.py when --render-video is set.
"""

import re
from pathlib import Path

from loguru import logger

from studioz.agents.narrator import agent_narrator
from studioz.clients.disclaimer_cards import generate_disclaimer_cards
from studioz.clients.tts_client import build_voice_map, generate_narration_audio
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
    # Use total word count per segment (narrator_text + dialogue line if present)
    word_counts = []
    for seg in narration.segments:
        wc = len(seg.narrator_text.split())
        if seg.dialogue:
            wc += len(seg.dialogue.line.split())
        word_counts.append(wc)

    total_words = sum(word_counts)

    if total_words == 0:
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


async def run_narration_pipeline(
    storyboard: Storyboard,
    on_stage: callable = None,
    job_id: str | None = None,
    estimated_runtime_minutes: int = 0,
    greenlit: bool = True,
    force_used: bool = False,
    rejection_summary: str | None = None,
) -> str | None:
    """
    Full narration-to-video pipeline:
    1. Generate narration script (table-read format) from storyboard
    2. Build character voice map
    3. Generate per-frame TTS audio and concatenate
    4. Measure audio duration
    5. Build per-frame timeline
    6. Assemble final video

    Returns path to the final .mp4 on success, None on failure.
    """
    safe_title = _safe_title(storyboard.title)
    total_frames = len(storyboard.frames)

    def _stage(name: str):
        if on_stage:
            on_stage(name)

    # Step 1: Generate narration script
    _stage("narration")
    print("\nRunning Narrator Agent...")
    narration = await agent_narrator(storyboard)

    print(f"\n[Narration Script] {len(narration.segments)} segments:")
    for seg in narration.segments:
        dialogue_info = ""
        if seg.dialogue:
            dialogue_info = f" | {seg.dialogue.character_name}: \"{seg.dialogue.line}\""
        print(f"  Frame {seg.frame_number}: {seg.narrator_text}{dialogue_info}")

    # Step 2: Build voice map
    voice_map = build_voice_map(narration.segments)
    if voice_map:
        print(f"\n[Voice Map]")
        for char, voice in voice_map.items():
            print(f"  {char} -> {voice}")
    else:
        print("\n[Voice Map] No character dialogue — narrator only.")

    # Step 3: Generate per-frame TTS audio (concatenated into one file)
    if job_id:
        audio_dir = Path("outputs/audio") / job_id
    else:
        audio_dir = Path("outputs/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(audio_dir / f"{safe_title}_narration.wav")

    _stage(f"tts:{total_frames}")
    print("\nGenerating narration audio via TTS (per-frame)...")
    result = await generate_narration_audio(narration.segments, voice_map, audio_path)
    if result is None:
        logger.error("TTS generation failed — cannot assemble video")
        print("[Video] TTS generation failed. Skipping video assembly.")
        return None

    # Step 4: Measure audio duration
    total_duration = await get_audio_duration(audio_path)
    if total_duration is None:
        logger.error("Could not measure audio duration — cannot assemble video")
        print("[Video] Could not measure audio duration. Skipping video assembly.")
        return None

    print(f"[Audio] Duration: {total_duration:.2f}s")

    # Step 5: Build per-frame timeline
    durations = _calculate_frame_durations(narration, total_duration)
    print(f"\n[Timeline] Per-frame durations (total={sum(durations):.2f}s):")
    for seg, dur in zip(narration.segments, durations):
        print(f"  Frame {seg.frame_number}: {dur:.2f}s")

    # Step 6: Assemble video
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

    if job_id:
        video_dir = Path("outputs/video") / job_id
    else:
        video_dir = VIDEO_OUTPUTS_DIR
    video_dir.mkdir(parents=True, exist_ok=True)
    video_path = str(video_dir / f"{safe_title}.mp4")

    _stage("video_assembly")
    print("\nAssembling video...")

    # Prepend disclaimer cards as silent pre-roll segments
    card_output_dir = str(video_dir / "_cards") if job_id else "outputs/_cards"
    disclaimer_cards = generate_disclaimer_cards(
        estimated_runtime_minutes=estimated_runtime_minutes,
        greenlit=greenlit,
        force_used=force_used,
        rejection_summary=rejection_summary,
        output_dir=card_output_dir,
    )
    if disclaimer_cards:
        card_paths = [path for path, _ in disclaimer_cards]
        card_durations = [dur for _, dur in disclaimer_cards]
        total_card_duration = sum(card_durations)
        frame_image_paths = card_paths + frame_image_paths
        frame_durations = card_durations + frame_durations
        print(f"[Video] Prepending {len(disclaimer_cards)} disclaimer card(s) ({total_card_duration:.1f}s)")

        # Prepend silence to the narration audio so it starts after the cards
        import wave
        import struct
        padded_audio_path = str(Path(audio_path).parent / f"{safe_title}_padded.wav")
        silence_samples = int(total_card_duration * 24000)  # 24kHz sample rate
        silence_bytes = struct.pack(f"<{silence_samples}h", *([0] * silence_samples))
        with wave.open(audio_path, "rb") as orig:
            params = orig.getparams()
            orig_data = orig.readframes(orig.getnframes())
        with wave.open(padded_audio_path, "wb") as padded:
            padded.setparams(params)
            padded.writeframes(silence_bytes + orig_data)
        audio_path = padded_audio_path
        print(f"[Video] Audio padded with {total_card_duration:.1f}s silence")

    result = await build_video(frame_image_paths, frame_durations, audio_path, video_path)
    if result is None:
        print("[Video] Assembly failed.")
        return None

    print(f"[Video] Final video saved: {video_path}")
    return video_path

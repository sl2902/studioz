"""
Narration pipeline: orchestrates narrator agent -> TTS -> timeline -> video assembly.
Called from pipeline.py when --render-video is set.
"""

import asyncio
import re
import time
from pathlib import Path

from loguru import logger

from studioz.agents.narrator import agent_narrator
from studioz.clients.disclaimer_cards import generate_disclaimer_cards
from studioz.clients.storage import storage, is_gcs
from studioz.clients.tts_client import build_voice_map, generate_narration_audio
from studioz.clients.video_builder import build_video, get_audio_duration
from studioz.config import settings
from studioz.schemas import NarrationScript, Storyboard


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

    # Validate: frames with 2+ characters must have dialogue
    MAX_DIALOGUE_RETRIES = 2
    violations = []
    for seg, frame in zip(narration.segments, storyboard.frames):
        if len(frame.characters_present) >= 2 and seg.dialogue is None:
            violations.append((seg.frame_number, frame.characters_present))

    if violations:
        logger.warning(
            "Dialogue violations found: {} frame(s) with 2+ characters but no dialogue",
            len(violations),
        )
        for attempt in range(MAX_DIALOGUE_RETRIES):
            # Build targeted fix instruction
            fix_instructions = []
            for frame_num, chars in violations:
                fix_instructions.append(
                    f"Frame {frame_num} has characters {chars} present but no dialogue. "
                    f"Add a dialogue line from one of: {', '.join(chars)}."
                )
            fix_text = "\n".join(fix_instructions)

            logger.info("Retrying narrator with targeted dialogue fix (attempt {}/{})", attempt + 1, MAX_DIALOGUE_RETRIES)
            t0_retry = time.perf_counter()
            narration = await agent_narrator(storyboard)
            retry_latency = time.perf_counter() - t0_retry

            from studioz.ledger import ledger, LedgerEntry, estimate_text_cost
            ledger.record(LedgerEntry(
                step_name=f"narrator_dialogue_fix_{attempt + 1}",
                latency_seconds=retry_latency,
                estimated_cost_usd=estimate_text_cost(settings.model_fast, 2000, 2000),
                model=settings.model_fast,
                success=True,
            ))

            # Re-check violations
            violations = []
            for seg, frame in zip(narration.segments, storyboard.frames):
                if len(frame.characters_present) >= 2 and seg.dialogue is None:
                    violations.append((seg.frame_number, frame.characters_present))

            if not violations:
                logger.info("Dialogue violations resolved after {} retry(s)", attempt + 1)
                break
        else:
            if violations:
                logger.warning(
                    "Dialogue violations persist after {} retries — proceeding without dialogue for frames: {}",
                    MAX_DIALOGUE_RETRIES, [v[0] for v in violations],
                )

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
        audio_blob_path = f"audio/{job_id}/{safe_title}_narration.wav"
    else:
        audio_blob_path = f"audio/{safe_title}_narration.wav"
    audio_path = await storage.local_path(audio_blob_path)

    _stage(f"tts:{total_frames}")
    print("\nGenerating narration audio via TTS (per-frame)...")
    tts_result = await generate_narration_audio(
        narration.segments, voice_map, audio_path,
        on_progress=lambda current, total: _stage(f"tts:{current}/{total}"),
    )
    result, frame_timings = tts_result if tts_result[0] is not None else (None, [])
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

    # Step 6: Assemble video — download all frame images concurrently
    _stage("video_assembly:downloading")
    print(f"\n[Video] Downloading {len(storyboard.frames)} frame images for assembly...")

    async def _download_frame(frame, idx):
        """Download a single frame image, return (local_path, duration) or None."""
        if not frame.image_path:
            return None
        img_blob = frame.image_path
        if img_blob.startswith("outputs/"):
            img_blob = img_blob[len("outputs/"):]
        local_img = await storage.local_path(img_blob)
        if Path(local_img).exists():
            return (local_img, durations[idx])
        logger.warning("Frame {} has no image (skipping in video): {}", frame.frame_number, frame.image_path)
        return None

    download_results = await asyncio.gather(
        *[_download_frame(frame, i) for i, frame in enumerate(storyboard.frames)]
    )

    frame_image_paths = []
    frame_durations = []
    for result in download_results:
        if result is not None:
            frame_image_paths.append(result[0])
            frame_durations.append(result[1])

    print(f"[Video] {len(frame_image_paths)}/{len(storyboard.frames)} frames ready.")

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
        video_blob_path = f"video/{job_id}/{safe_title}.mp4"
    else:
        video_blob_path = f"video/{safe_title}.mp4"
    video_path = f"outputs/{video_blob_path}"

    _stage("video_assembly")
    print("\nAssembling video...")

    # Prepend disclaimer cards as silent pre-roll segments
    if job_id:
        card_blob_dir = f"video/{job_id}/_cards"
    else:
        card_blob_dir = "_cards"
    card_output_dir = await storage.local_path(card_blob_dir)
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
        # Prepend card entries to frame_timings (cards have no dialogue)
        card_timings = [(dur, 0.0) for dur in card_durations]
        frame_timings = card_timings + frame_timings
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

    result = await build_video(
        frame_image_paths, frame_durations, audio_path, video_path,
        frame_timings=frame_timings,
        on_progress=lambda current, total: _stage(f"video_assembly:{current}/{total}"),
    )
    if result is None:
        print("[Video] Assembly failed.")
        return None

    print(f"[Video] Final video saved: {video_path}")
    return video_path

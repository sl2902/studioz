import asyncio
import tempfile
from pathlib import Path

from loguru import logger

from studioz.clients.storage import storage, is_gcs


async def _run_ffmpeg(args: list[str]) -> bool:
    """Run an ffmpeg/ffprobe command, return True on success."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error("ffmpeg failed: {}", stderr.decode()[-500:])
        return False
    return True


async def get_audio_duration(audio_path: str) -> float | None:
    """Get duration of an audio file in seconds using ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "compact=print_section=0:nokey=1",
        "-show_entries", "format=duration", audio_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("ffprobe failed for '{}'", audio_path)
        return None
    try:
        return float(stdout.decode().strip())
    except ValueError:
        logger.warning("Could not parse duration from ffprobe output: '{}'", stdout.decode())
        return None


async def build_video(
    frame_image_paths: list[str],
    frame_durations: list[float],
    narration_audio_path: str,
    output_path: str,
    frame_timings: list[tuple[float, float]] | None = None,
) -> str | None:
    """
    Assemble a narrated video from frame images + audio.

    Strategy:
    1. Create a silent video segment per frame (static image held for its duration).
       For frames with dialogue (frame_timings[i][1] > 0), split into two segments:
       narrator portion (plain image) then dialogue portion (image + bubble overlay).
    2. Concatenate all segments via the concat demuxer.
    3. Mux the single continuous narration audio into the final video.

    Returns the output path on success, None on failure.
    """
    from studioz.clients.speech_bubble import generate_bubble_overlay

    # Resolve output path via storage backend
    blob_path = output_path
    if blob_path.startswith("outputs/"):
        blob_path = blob_path[len("outputs/"):]
    local_output = storage.local_path(blob_path)

    # Generate bubble overlay (once, cached)
    bubble_path = generate_bubble_overlay()

    with tempfile.TemporaryDirectory(prefix="studioz_video_") as tmp_dir:
        tmp = Path(tmp_dir)
        segment_paths = []
        segment_idx = 0

        # Step 1: Create per-frame silent video segments
        for i, (img_path, duration) in enumerate(zip(frame_image_paths, frame_durations)):
            # Check if this frame has a dialogue portion
            has_dialogue = (
                frame_timings is not None
                and i < len(frame_timings)
                and frame_timings[i][1] > 0.0
            )

            if has_dialogue:
                narrator_dur, dialogue_dur = frame_timings[i]
                # Narrator portion: plain image
                if narrator_dur > 0:
                    seg_path = str(tmp / f"segment_{segment_idx:03d}.mp4")
                    success = await _run_ffmpeg([
                        "ffmpeg", "-y",
                        "-loop", "1", "-i", img_path,
                        "-t", f"{narrator_dur:.3f}",
                        "-vf", "scale=1376:768:force_original_aspect_ratio=decrease,pad=1376:768:(ow-iw)/2:(oh-ih)/2",
                        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "24",
                        seg_path,
                    ])
                    if not success:
                        logger.error("Failed to create narrator segment for frame {}", i + 1)
                        return None
                    segment_paths.append(seg_path)
                    segment_idx += 1

                # Dialogue portion: image + bubble overlay
                seg_path = str(tmp / f"segment_{segment_idx:03d}.mp4")
                success = await _run_ffmpeg([
                    "ffmpeg", "-y",
                    "-loop", "1", "-i", img_path,
                    "-loop", "1", "-i", bubble_path,
                    "-t", f"{dialogue_dur:.3f}",
                    "-filter_complex",
                    "[0]scale=1376:768:force_original_aspect_ratio=decrease,pad=1376:768:(ow-iw)/2:(oh-ih)/2,format=rgb24[base];"
                    "[1]format=rgba[overlay];"
                    "[base][overlay]overlay=0:0",
                    "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "24",
                    seg_path,
                ])
                if not success:
                    logger.error("Failed to create dialogue segment for frame {}", i + 1)
                    return None
                segment_paths.append(seg_path)
                segment_idx += 1
            else:
                # No dialogue: single segment, plain image
                seg_path = str(tmp / f"segment_{segment_idx:03d}.mp4")
                success = await _run_ffmpeg([
                    "ffmpeg", "-y",
                    "-loop", "1", "-i", img_path,
                    "-t", f"{duration:.3f}",
                    "-vf", "scale=1376:768:force_original_aspect_ratio=decrease,pad=1376:768:(ow-iw)/2:(oh-ih)/2",
                    "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "24",
                    seg_path,
                ])
                if not success:
                    logger.error("Failed to create video segment for frame {}", i + 1)
                    return None
                segment_paths.append(seg_path)
                segment_idx += 1

            logger.debug("Created segment(s) for frame {}: {}s", i + 1, f"{duration:.2f}")

        # Step 2: Write concat list
        concat_list_path = str(tmp / "concat_list.txt")
        with open(concat_list_path, "w") as f:
            for seg in segment_paths:
                f.write(f"file '{seg}'\n")

        # Step 3: Concatenate segments and mux narration audio
        success = await _run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_list_path,
            "-i", narration_audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            local_output,
        ])

        if not success:
            logger.error("Failed to mux final video")
            return None

        # Upload to GCS if needed
        if is_gcs():
            await storage.upload_local_file(local_output, blob_path, "video/mp4")

        logger.success("Video assembled: {}", blob_path)
        return output_path

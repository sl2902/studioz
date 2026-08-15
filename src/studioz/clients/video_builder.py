import asyncio
import tempfile
from pathlib import Path

from loguru import logger


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
) -> str | None:
    """
    Assemble a narrated video from frame images + audio.

    Strategy:
    1. Create a silent video segment per frame (static image held for its duration).
    2. Concatenate all segments via the concat demuxer.
    3. Mux the single continuous narration audio into the final video.

    Returns the output path on success, None on failure.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="studioz_video_") as tmp_dir:
        tmp = Path(tmp_dir)
        segment_paths = []

        # Step 1: Create per-frame silent video segments
        for i, (img_path, duration) in enumerate(zip(frame_image_paths, frame_durations)):
            segment_path = str(tmp / f"segment_{i:02d}.mp4")
            success = await _run_ffmpeg([
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", img_path,
                "-t", f"{duration:.3f}",
                "-vf", "scale=1376:768:force_original_aspect_ratio=decrease,pad=1376:768:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264",
                "-preset", "medium",
                "-pix_fmt", "yuv420p",
                "-r", "24",
                segment_path,
            ])
            if not success:
                logger.error("Failed to create video segment for frame {}", i + 1)
                return None
            segment_paths.append(segment_path)
            logger.debug("Created segment {}: {}s", i + 1, f"{duration:.2f}")

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
            "-shortest",
            output_path,
        ])

        if not success:
            logger.error("Failed to mux final video")
            return None

        logger.success("Video assembled: {}", output_path)
        return output_path

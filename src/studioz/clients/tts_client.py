import wave
from pathlib import Path

from google.genai import types
from loguru import logger

from studioz.clients.vertex_client import client

# Gemini native TTS model — try the preview TTS model first.
# If this 404s, check current available models in Vertex AI.
TTS_MODEL = "gemini-2.5-flash-preview-tts"

# Voice to use for narration — Kore is a clear, neutral narrator voice.
TTS_VOICE = "Kore"

# Gemini TTS returns raw 16-bit PCM at 24000 Hz, mono.
_PCM_CHANNELS = 1
_PCM_SAMPLE_RATE = 24000
_PCM_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes


def _write_wav_file(
    filename: str,
    pcm_data: bytes,
    channels: int = _PCM_CHANNELS,
    rate: int = _PCM_SAMPLE_RATE,
    sample_width: int = _PCM_SAMPLE_WIDTH,
) -> None:
    """Wrap raw PCM bytes in a proper WAV container."""
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)


async def generate_narration_audio(full_narration_text: str, output_path: str) -> str | None:
    """
    Generates a single continuous speech audio file via Gemini native TTS,
    saves as .wav at output_path. Returns None on failure (logs a warning,
    doesn't crash the run).
    """
    try:
        logger.info("Generating narration audio ({} chars) -> {}", len(full_narration_text), output_path)

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        response = await client.aio.models.generate_content(
            model=TTS_MODEL,
            contents=full_narration_text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=TTS_VOICE,
                        )
                    )
                ),
            ),
        )

        if not response.candidates:
            block_reason = getattr(response, "prompt_feedback", None)
            logger.warning(
                "TTS generation failed: no candidates returned. prompt_feedback={}",
                block_reason,
            )
            return None

        # Extract audio data from response parts
        audio_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                audio_bytes = part.inline_data.data
                break

        if audio_bytes is None:
            logger.warning("TTS generation failed: no audio data in response parts")
            return None

        _write_wav_file(output_path, audio_bytes)
        logger.success("Narration audio saved: {} ({} bytes PCM + WAV header)", output_path, len(audio_bytes))
        return output_path

    except Exception as e:
        logger.warning("TTS generation failed: {}", e)
        return None

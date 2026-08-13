import time
import wave
from pathlib import Path

from google.genai import types
from loguru import logger

from studioz.clients.vertex_client import client
from studioz.ledger import ledger, LedgerEntry, estimate_tts_cost
from studioz.schemas import NarrationSegment

# Gemini TTS model with audio tag support.
# gemini-3.1-flash-tts-preview confirmed to support audio tags ([whispers], etc.)
# If this 404s, fall back to gemini-2.5-flash-preview-tts.
TTS_MODEL = "gemini-3.1-flash-tts-preview"

# Fixed narrator voice
NARRATOR_VOICE = "Kore"

# Voice pools classified by perceived gender.
# Classified by actual listening tests (Google's docs are inaccurate).
# Voices confirmed by ear: Charon, Orus, Puck, Aoede = male-sounding.
# Fenrir sounds androgynous/female despite being listed as "Male" in docs.
MALE_VOICES = ["Charon", "Orus", "Puck", "Algenib", "Rasalgethi",
               "Achird", "Sadaltager"]
FEMALE_VOICES = ["Leda", "Fenrir", "Aoede", "Despina", "Erinome", "Laomedeia",
                 "Achernar", "Pulcherrima", "Schedar", "Vindemiatrix", "Zephyr"]
NEUTRAL_VOICES = ["Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel",
                  "Algieba", "Alnilam", "Gacrux", "Zubenelgenubi", "Sadachbia",
                  "Sulafat"]

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


def build_voice_map(segments: list[NarrationSegment]) -> dict[str, str]:
    """
    Builds a character_name -> voice_name mapping. Assigns from the
    gender-matching voice pool the first time a character is encountered,
    keeping the same voice for that character across all frames.
    Narrator always uses NARRATOR_VOICE (not in this map).
    """
    voice_map: dict[str, str] = {}
    # Track next index per pool to avoid reuse
    pool_indices = {"male": 0, "female": 0, "neutral": 0}
    pools = {"male": MALE_VOICES, "female": FEMALE_VOICES, "neutral": NEUTRAL_VOICES}

    for seg in segments:
        if seg.dialogue and seg.dialogue.character_name not in voice_map:
            gender = seg.dialogue.character_gender
            pool = pools[gender]
            idx = pool_indices[gender]
            # Wrap around if pool exhausted
            voice_map[seg.dialogue.character_name] = pool[idx % len(pool)]
            pool_indices[gender] = idx + 1

    return voice_map


async def _generate_single_speaker_pcm(text: str, voice: str = NARRATOR_VOICE) -> bytes | None:
    """Generate PCM for a single-speaker frame (narrator only, no dialogue)."""
    try:
        response = await client.aio.models.generate_content(
            model=TTS_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice,
                        )
                    )
                ),
            ),
        )

        if not response.candidates:
            block_reason = getattr(response, "prompt_feedback", None)
            logger.warning("TTS single-speaker failed: no candidates. prompt_feedback={}", block_reason)
            return None

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                return part.inline_data.data

        logger.warning("TTS single-speaker failed: no audio data in response")
        return None

    except Exception as e:
        logger.warning("TTS single-speaker failed: {}", e)
        return None


async def _generate_multi_speaker_pcm(
    segment: NarrationSegment,
    character_voice: str,
) -> bytes | None:
    """
    Generate PCM for a multi-speaker frame (Narrator + one character).

    Strategy: Generate each speaker's audio via separate single-speaker calls
    to guarantee the correct voice is used for each. The Gemini multi-speaker
    API has a known bug where voice_name assignments are intermittently ignored
    (see https://discuss.ai.google.dev/t/84125). Separate calls are reliable.
    """
    # Generate narrator portion
    narrator_pcm = await _generate_single_speaker_pcm(
        segment.narrator_text, NARRATOR_VOICE
    )
    if narrator_pcm is None:
        logger.warning(
            "TTS frame {}: narrator portion failed", segment.frame_number
        )
        return None

    # Generate character dialogue portion
    character_pcm = await _generate_single_speaker_pcm(
        segment.dialogue.line, character_voice
    )
    if character_pcm is None:
        logger.warning(
            "TTS frame {}: character '{}' portion failed",
            segment.frame_number, segment.dialogue.character_name,
        )
        # Fall back to narrator-only if character fails
        return narrator_pcm

    # Concatenate: narrator audio then character audio
    return narrator_pcm + character_pcm


async def generate_narration_audio(
    segments: list[NarrationSegment],
    voice_map: dict[str, str],
    output_path: str,
) -> str | None:
    """
    Generates speech audio per frame (one TTS call each, respecting
    the 2-speaker-per-call limit), concatenates all raw PCM into a
    single continuous WAV file.

    - Frames with no dialogue: single-speaker call (Narrator only)
    - Frames with dialogue: multi-speaker call (Narrator + character)

    Returns output_path on success, None if all segments fail.
    """
    logger.info(
        "Generating narration audio ({} segments, {} characters) -> {}",
        len(segments), len(voice_map), output_path,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    all_pcm = bytearray()
    succeeded = 0

    for i, seg in enumerate(segments):
        t0 = time.perf_counter()
        if seg.dialogue and seg.dialogue.character_name in voice_map:
            # Multi-speaker: Narrator + character
            character_voice = voice_map[seg.dialogue.character_name]
            logger.info(
                "TTS frame {}: Narrator + '{}' (gender={}, voice={})",
                seg.frame_number, seg.dialogue.character_name,
                seg.dialogue.character_gender, character_voice,
            )
            pcm = await _generate_multi_speaker_pcm(seg, character_voice)
        else:
            # Single speaker: Narrator only
            logger.info("TTS frame {}: Narrator only", seg.frame_number)
            pcm = await _generate_single_speaker_pcm(seg.narrator_text)

        latency = time.perf_counter() - t0
        if pcm is not None:
            all_pcm.extend(pcm)
            succeeded += 1
            # Estimate tokens based on text length (rough: 1 token ≈ 4 chars)
            input_text = seg.narrator_text + (seg.dialogue.line if seg.dialogue else "")
            estimated_input_tokens = len(input_text) // 4
            estimated_output_tokens = len(pcm) // 2  # 16-bit samples
            cost = estimate_tts_cost(estimated_input_tokens, estimated_output_tokens)
            ledger.record(LedgerEntry(
                step_name=f"tts_frame_{seg.frame_number}",
                latency_seconds=latency,
                estimated_cost_usd=cost,
                model="gemini-3.1-flash-tts-preview",
                success=True,
            ))
        else:
            ledger.record(LedgerEntry(
                step_name=f"tts_frame_{seg.frame_number}",
                latency_seconds=latency,
                estimated_cost_usd=0.0,
                model="gemini-3.1-flash-tts-preview",
                success=False,
            ))
            logger.warning("TTS frame {} failed — gap in audio", seg.frame_number)

    if succeeded == 0:
        logger.error("All TTS segments failed — no audio generated")
        return None

    _write_wav_file(output_path, bytes(all_pcm))
    logger.success(
        "Narration audio saved: {} ({}/{} frames, {} bytes PCM)",
        output_path, succeeded, len(segments), len(all_pcm),
    )
    return output_path

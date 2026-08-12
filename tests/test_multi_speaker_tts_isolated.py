"""
Isolated multi-speaker TTS test — split single-speaker approach.

Generates narrator and character audio as SEPARATE single-speaker calls
to guarantee distinct voices, then concatenates the PCM.

Run with:
    python tests/test_multi_speaker_tts_isolated.py

Output: tests/output/multi_speaker_split_test.wav
"""

import asyncio
import wave
from pathlib import Path

from google import genai
from google.genai import types

from studioz.config import settings

# Constants matching tts_client.py
TTS_MODEL = "gemini-3.1-flash-tts-preview"
PCM_CHANNELS = 1
PCM_SAMPLE_RATE = 24000
PCM_SAMPLE_WIDTH = 2

# Two voices that should be VERY different
NARRATOR_VOICE = "Kore"   # Female / firm
CHARACTER_VOICE = "Fenrir"  # Male / excitable

NARRATOR_TEXT = "The dark corridor stretched endlessly before them."
CHARACTER_LINE = "We need to get out of here, now."


def write_wav(path: str, pcm_data: bytes) -> None:
    """Wrap raw PCM bytes in a WAV container."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(PCM_CHANNELS)
        wf.setsampwidth(PCM_SAMPLE_WIDTH)
        wf.setframerate(PCM_SAMPLE_RATE)
        wf.writeframes(pcm_data)


async def generate_single_speaker(client_inst, text: str, voice: str) -> bytes | None:
    """Generate PCM for a single speaker."""
    response = await client_inst.aio.models.generate_content(
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
        return None

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
            return part.inline_data.data
    return None


async def run_test():
    client_inst = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
    )

    print("=" * 60)
    print("SPLIT SINGLE-SPEAKER TTS TEST")
    print("=" * 60)
    print(f"\nModel: {TTS_MODEL}")
    print(f"Narrator: voice={NARRATOR_VOICE!r}, text={NARRATOR_TEXT!r}")
    print(f"Character: voice={CHARACTER_VOICE!r}, text={CHARACTER_LINE!r}")
    print(f"\nGenerating narrator audio...")

    narrator_pcm = await generate_single_speaker(client_inst, NARRATOR_TEXT, NARRATOR_VOICE)
    if narrator_pcm is None:
        print("FAILED: Narrator generation returned no audio.")
        return

    print(f"  Narrator PCM: {len(narrator_pcm)} bytes ({len(narrator_pcm) / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH):.1f}s)")

    print(f"Generating character audio...")
    character_pcm = await generate_single_speaker(client_inst, CHARACTER_LINE, CHARACTER_VOICE)
    if character_pcm is None:
        print("FAILED: Character generation returned no audio.")
        return

    print(f"  Character PCM: {len(character_pcm)} bytes ({len(character_pcm) / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH):.1f}s)")

    # Concatenate
    combined_pcm = narrator_pcm + character_pcm

    output_dir = Path("tests/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "multi_speaker_split_test.wav"
    write_wav(str(output_path), combined_pcm)

    duration = len(combined_pcm) / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH * PCM_CHANNELS)
    print(f"\nSUCCESS!")
    print(f"  Output: {output_path}")
    print(f"  Total duration: {duration:.1f}s")
    print(f"\nListen — you should hear Kore (female) then Fenrir (male) distinctly.")


if __name__ == "__main__":
    asyncio.run(run_test())

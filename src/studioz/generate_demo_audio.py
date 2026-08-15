"""
Generate and cache narration audio for the pipeline explainer steps
and golden demo walkthrough.

Usage:
    python -m studioz.generate_demo_audio

Generates:
    outputs/_assets/explainer_voice/{step_id}.wav — one per explainer step
    outputs/_assets/demo_walkthrough/{golden_job_id}.wav — one per golden demo

Reuses existing TTS client (Gemini 3.1 Flash TTS, single-speaker).
"""

import asyncio
import json
import wave
from pathlib import Path

from loguru import logger

from studioz.clients.tts_client import _generate_single_speaker_pcm, _write_wav_file


# Explainer script — first-person narration per stage
EXPLAINER_STEPS = [
    {"id": "intro", "voice": "Kore", "text":
        "This is StudioZ — a multi-agent AI system that turns a single pitch "
        "into a fully negotiated, previsualized film concept. It's built for "
        "solo creators, indie studios, and small production teams who need "
        "to test an idea's creative, financial, and legal viability before "
        "committing real budget. Here's how it works."},
    {"id": "screenwriter", "voice": "Kore", "text":
        "I'm the Screenwriter. I take your pitch and draft a full script "
        "treatment — title, genre, logline, and a three-act synopsis."},
    {"id": "grounding", "voice": "Kore", "text":
        "Before the committee weighs in, I ground this treatment in reality — "
        "real box office comparables, market trends, and IP precedent, sourced "
        "live through the Parallel Search API."},
    {"id": "committee_cfo", "voice": "Charon", "text":
        "I'm the CFO. My job is to protect the budget — I'll tell you "
        "exactly where this project could lose money."},
    {"id": "committee_creative", "voice": "Puck", "text":
        "I'm the Head of Creative Development. I'm looking for the "
        "spark — the idea that makes this worth making."},
    {"id": "committee_legal", "voice": "Orus", "text":
        "I'm VP of Legal. I check for IP conflicts, rating risk, and "
        "anything that could get us sued."},
    {"id": "consensus", "voice": "Kore", "text":
        "I'm the Committee Chair. I take all three perspectives — "
        "budget, creative, legal — and synthesize them into one final "
        "decision."},
    {"id": "gate", "voice": "Kore", "text":
        "This is the greenlight gate. If a project isn't approved, "
        "production stops here — unless it's deliberately overridden "
        "for testing."},
    {"id": "director", "voice": "Kore", "text":
        "I'm the Director. Once a project is greenlit, I break the "
        "story into key visual beats and write the shot list."},
    {"id": "image_generation", "voice": "Kore", "text":
        "For each beat, I generate a storyboard frame — then an "
        "inspector reviews it, and if something's off, I get specific "
        "feedback and try again before you ever see a wasted frame."},
    {"id": "narration", "voice": "Kore", "text":
        "I'm the Narrator. I write the spoken script for the final "
        "video — setting each scene, and giving dialogue to characters "
        "when there's a real exchange happening."},
    {"id": "tts", "voice": "Kore", "text":
        "I turn that script into voice — one voice for the narrator, "
        "and real, distinct voices for every character who speaks."},
    {"id": "video_assembly", "voice": "Kore", "text":
        "Finally, I stitch the frames, the audio, and a few context "
        "cards together into one finished video."},
]

EXPLAINER_CACHE_DIR = Path("outputs/_assets/explainer_voice")
DEMO_WALKTHROUGH_DIR = Path("outputs/_assets/demo_walkthrough")


async def generate_explainer_audio():
    """Generate and cache narration for each explainer step."""
    EXPLAINER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for step in EXPLAINER_STEPS:
        wav_path = EXPLAINER_CACHE_DIR / f"{step['id']}.wav"
        if wav_path.exists():
            print(f"  ✓ {step['id']} (cached)")
            continue

        print(f"  Generating: {step['id']}...", end=" ", flush=True)
        pcm = await _generate_single_speaker_pcm(step["text"], step["voice"])
        if pcm:
            _write_wav_file(str(wav_path), pcm)
            duration = len(pcm) / (24000 * 2)
            print(f"done ({duration:.1f}s)")
        else:
            print("FAILED")
            logger.warning("Failed to generate explainer audio for step: {}", step["id"])


async def generate_demo_walkthrough(golden_job_id: str | None = None):
    """Generate walkthrough narration for the golden demo result."""
    DEMO_WALKTHROUGH_DIR.mkdir(parents=True, exist_ok=True)

    # Find the golden job_id
    pointer_path = Path("demo_results/golden_job_id.txt")
    if golden_job_id is None:
        if not pointer_path.exists():
            print("  No golden demo set — skipping walkthrough generation.")
            return
        golden_job_id = pointer_path.read_text().strip()

    wav_path = DEMO_WALKTHROUGH_DIR / f"{golden_job_id}.wav"
    if wav_path.exists():
        print(f"  ✓ Demo walkthrough (cached for {golden_job_id[:8]})")
        return

    # Load the golden manifest
    manifest_path = Path("outputs/jobs") / golden_job_id / "manifest.json"
    if not manifest_path.exists():
        print(f"  Manifest not found for {golden_job_id[:8]} — skipping.")
        return

    manifest = json.loads(manifest_path.read_text())

    # Build walkthrough narration from real data
    treatment = manifest.get("treatment", {})
    review = manifest.get("executive_review", {})
    citations = manifest.get("grounding_citations", {})
    storyboard = manifest.get("storyboard", {})

    title = treatment.get("title", "this project")
    greenlight = "greenlit" if review.get("greenlight") else "not greenlit"
    budget = review.get("estimated_budget_millions", 0)
    citation_count = (
        len(citations.get("budget_comps", [])) +
        len(citations.get("market_trends", [])) +
        len(citations.get("ip_clearance", []))
    )
    frame_count = len(storyboard.get("frames", []))
    passed_count = sum(1 for f in storyboard.get("frames", []) if f.get("inspection_passed", True))

    # Ledger data
    ledger_entries = manifest.get("ledger_entries", [])
    ledger_totals = manifest.get("ledger_totals", {})
    num_calls = len(ledger_entries)
    total_latency = ledger_totals.get("total_latency_seconds", 0)
    total_cost = ledger_totals.get("total_cost_usd", 0)

    walkthrough_text = (
        f"Here's the result for {title}. "
        f"The committee {greenlight} it with an estimated budget of {budget} million dollars. "
        f"Their decision was grounded by {citation_count} real citations from Parallel Search — "
        f"covering box office comparables, market trends, and IP clearance. "
        f"The Director generated {frame_count} storyboard frames, "
        f"and {passed_count} of {frame_count} passed automated quality inspection. "
        f"This entire pipeline — from pitch to storyboard — ran {num_calls} API calls "
        f"across Vertex AI and Parallel Search, completing in {total_latency:.0f} seconds "
        f"for a total estimated cost of {total_cost:.2f} dollars. "
        f"Let's watch the final narrated video."
    )

    print(f"  Generating walkthrough for '{title}'...", end=" ", flush=True)
    pcm = await _generate_single_speaker_pcm(walkthrough_text, "Kore")
    if pcm:
        _write_wav_file(str(wav_path), pcm)
        duration = len(pcm) / (24000 * 2)
        print(f"done ({duration:.1f}s)")
    else:
        print("FAILED")


async def main():
    print("Generating explainer step audio:")
    await generate_explainer_audio()
    print("\nGenerating demo walkthrough audio:")
    await generate_demo_walkthrough()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

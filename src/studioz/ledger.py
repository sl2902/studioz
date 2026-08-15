from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class LedgerEntry:
    step_name: str
    latency_seconds: float
    estimated_cost_usd: float
    model: str
    success: bool


class Ledger:
    """Simple in-memory tracker for one pipeline run."""

    def __init__(self):
        self._entries: list[LedgerEntry] = []

    def record(self, entry: LedgerEntry) -> None:
        self._entries.append(entry)

    def to_dict_list(self) -> list[dict]:
        """Return entries as a list of dicts for JSON serialization."""
        return [
            {
                "step_name": e.step_name,
                "model": e.model,
                "latency_seconds": round(e.latency_seconds, 1),
                "estimated_cost_usd": round(e.estimated_cost_usd, 4),
                "success": e.success,
            }
            for e in self._entries
        ]

    def totals(self) -> dict:
        """Return total latency and cost."""
        total_latency = sum(e.latency_seconds for e in self._entries)
        total_cost = sum(e.estimated_cost_usd for e in self._entries)
        return {
            "total_latency_seconds": round(total_latency, 1),
            "total_cost_usd": round(total_cost, 4),
        }

    def summary(self) -> str:
        if not self._entries:
            return "[Ledger] No entries recorded."

        lines = []
        lines.append("\n" + "=" * 80)
        lines.append("PIPELINE COST/LATENCY LEDGER")
        lines.append("=" * 80)
        lines.append(f"{'Step':<35} {'Model':<30} {'Latency':>8} {'Cost':>10} {'Status':>8}")
        lines.append("-" * 80)

        total_latency = 0.0
        total_cost = 0.0

        for e in self._entries:
            status = "✓" if e.success else "✗"
            lines.append(
                f"{e.step_name:<35} {e.model:<30} {e.latency_seconds:>7.1f}s ${e.estimated_cost_usd:>8.4f} {status:>8}"
            )
            total_latency += e.latency_seconds
            total_cost += e.estimated_cost_usd

        lines.append("-" * 80)
        lines.append(
            f"{'TOTAL':<35} {'':<30} {total_latency:>7.1f}s ${total_cost:>8.4f}"
        )
        lines.append("=" * 80)
        return "\n".join(lines)


# Module-level singleton for the current pipeline run.
# Reset at the start of each run_studioz_pipeline call.
ledger = Ledger()


# Pricing constants (Paid Tier, Standard — from Google docs, Aug 2026)
# Text models: per million tokens
PRICING = {
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-3-pro-image": {"input": 2.00, "output_per_image": 0.134},
    "gemini-3.1-flash-tts-preview": {"input": 1.00, "output": 20.00},
    "parallel_search": {"per_call": 0.0},  # External API, pricing unclear — placeholder
}


def estimate_text_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost for a text model call based on token counts."""
    rates = PRICING.get(model, {"input": 0.0, "output": 0.0})
    if "output_per_image" in rates:
        return rates["output_per_image"]  # image model — flat per-image
    input_cost = (input_tokens / 1_000_000) * rates.get("input", 0.0)
    output_cost = (output_tokens / 1_000_000) * rates.get("output", 0.0)
    return input_cost + output_cost


def estimate_image_cost() -> float:
    """Estimate cost for one image generation call (gemini-3-pro-image at 1K)."""
    return 0.134


def estimate_tts_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate cost for one TTS call."""
    rates = PRICING["gemini-3.1-flash-tts-preview"]
    input_cost = (input_tokens / 1_000_000) * rates["input"]
    output_cost = (output_tokens / 1_000_000) * rates["output"]
    return input_cost + output_cost

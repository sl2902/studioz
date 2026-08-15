"""
Deterministic disclaimer card generation for video pre-rolls.

Generates simple text-on-dark-background images that are prepended to
videos as silent segments, providing factual context about what the
viewer is watching.
"""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# Match the video frame dimensions
CARD_WIDTH = 1376
CARD_HEIGHT = 768
CARD_BG_COLOR = (15, 15, 26)  # Dark navy, matching the app's bg
CARD_TEXT_COLOR = (200, 200, 210)  # Light grey
CARD_ACCENT_COLOR = (99, 102, 241)  # Indigo accent
CARD_DURATION = 4.0  # seconds each card is shown


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a font, falling back to default if no system font is found."""
    # Try common system fonts
    font_paths = [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _render_card(lines: list[str], output_path: str) -> str:
    """Render a disclaimer card with the given text lines."""
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), CARD_BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title font and body font
    title_font = _get_font(28)
    body_font = _get_font(22)

    # Calculate vertical centering
    line_height = 36
    total_height = len(lines) * line_height
    y_start = (CARD_HEIGHT - total_height) // 2

    # Draw a subtle top/bottom border line
    draw.line([(100, y_start - 40), (CARD_WIDTH - 100, y_start - 40)], fill=CARD_ACCENT_COLOR, width=1)
    draw.line([(100, y_start + total_height + 20), (CARD_WIDTH - 100, y_start + total_height + 20)], fill=CARD_ACCENT_COLOR, width=1)

    # Draw text lines centered
    for i, line in enumerate(lines):
        font = title_font if i == 0 else body_font
        color = CARD_ACCENT_COLOR if i == 0 else CARD_TEXT_COLOR
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (CARD_WIDTH - text_width) // 2
        y = y_start + i * line_height
        draw.text((x, y), line, fill=color, font=font)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


def generate_disclaimer_cards(
    estimated_runtime_minutes: int,
    greenlit: bool,
    force_used: bool,
    rejection_summary: str | None = None,
    output_dir: str = "outputs/_cards",
) -> list[tuple[str, float]]:
    """
    Generate disclaimer card images and return list of (image_path, duration) tuples
    to prepend to the video frame list.

    Returns:
        List of (image_path, duration_seconds) for each card to prepend.
    """
    cards: list[tuple[str, float]] = []
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Card A — always shown: runtime context
    card_a_lines = [
        "CONCEPT PREVIEW",
        "",
        f"Target film runtime: {estimated_runtime_minutes} minutes",
        "",
        "This video is a short pitch previz,",
        "not the full film.",
    ]
    card_a_path = _render_card(card_a_lines, str(out / "card_a_runtime.png"))
    cards.append((card_a_path, CARD_DURATION))

    # Card B — only shown when force was used to bypass a real rejection
    if not greenlit and force_used:
        card_b_lines = [
            "DEMONSTRATION ONLY",
            "",
            "This preview was generated for demonstration purposes.",
            "The StudioZ committee did not greenlight this project.",
        ]
        if rejection_summary:
            # Wrap the first sentence of the rejection summary
            first_sentence = rejection_summary.split(".")[0] + "."
            wrapped = textwrap.wrap(first_sentence, width=60)
            card_b_lines.append("")
            card_b_lines.extend(wrapped[:2])  # Max 2 lines of summary

        card_b_path = _render_card(card_b_lines, str(out / "card_b_rejection.png"))
        cards.append((card_b_path, 5.0))  # Slightly longer to read

    return cards

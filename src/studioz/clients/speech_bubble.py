"""
Generate a static speech bubble overlay PNG (transparent background).
Used during video assembly to indicate character dialogue is playing.
"""

from pathlib import Path
from PIL import Image, ImageDraw


# Overlay dimensions match video frame size
FRAME_WIDTH = 1376
FRAME_HEIGHT = 768

# Bubble position: bottom-right corner, with padding
BUBBLE_PADDING = 40
BUBBLE_WIDTH = 160
BUBBLE_HEIGHT = 100
BUBBLE_RADIUS = 20
BUBBLE_OUTLINE_COLOR = (20, 20, 40, 255)  # Solid dark outline
BUBBLE_FILL_COLOR = (20, 20, 40, 160)  # Semi-transparent dark fill — visible on both white and dark backgrounds
BUBBLE_OUTLINE_WIDTH = 4
BUBBLE_TAIL_SIZE = 15


def generate_bubble_overlay(output_path: str = "outputs/_assets/speech_bubble.png") -> str:
    """
    Generate a transparent PNG with a speech bubble in the bottom-right corner.
    Reused across all frames that need it (generated once, cached).
    """
    path = Path(output_path)
    if path.exists():
        return str(path)

    path.parent.mkdir(parents=True, exist_ok=True)

    # Create transparent image
    img = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Position bubble in bottom-right
    x1 = FRAME_WIDTH - BUBBLE_PADDING - BUBBLE_WIDTH
    y1 = FRAME_HEIGHT - BUBBLE_PADDING - BUBBLE_HEIGHT - BUBBLE_TAIL_SIZE
    x2 = FRAME_WIDTH - BUBBLE_PADDING
    y2 = y1 + BUBBLE_HEIGHT

    # Draw rounded rectangle bubble with fill
    draw.rounded_rectangle(
        [x1, y1, x2, y2],
        radius=BUBBLE_RADIUS,
        fill=BUBBLE_FILL_COLOR,
        outline=BUBBLE_OUTLINE_COLOR,
        width=BUBBLE_OUTLINE_WIDTH,
    )

    # Draw tail (small triangle pointing down-left)
    tail_x = x1 + BUBBLE_WIDTH // 3
    tail_points = [
        (tail_x, y2),
        (tail_x - BUBBLE_TAIL_SIZE, y2 + BUBBLE_TAIL_SIZE),
        (tail_x + BUBBLE_TAIL_SIZE, y2),
    ]
    draw.polygon(tail_points, fill=BUBBLE_FILL_COLOR, outline=BUBBLE_OUTLINE_COLOR)
    # Draw tail outline lines individually to match the width
    draw.line([tail_points[0], tail_points[1]], fill=BUBBLE_OUTLINE_COLOR, width=BUBBLE_OUTLINE_WIDTH)
    draw.line([tail_points[1], tail_points[2]], fill=BUBBLE_OUTLINE_COLOR, width=BUBBLE_OUTLINE_WIDTH)

    img.save(str(path), "PNG")
    return str(path)

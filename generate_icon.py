"""Generate a nice application icon as .ico file using Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

SIZE = 256
ICON_PATH = str(Path(__file__).resolve().parent / "app_icon.ico")


def _rounded_rect(draw, xy, radius, fill):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def generate_icon():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # -- Background: rounded rect with gradient feel --
    margin = 12
    bg_color = (30, 50, 100)  # deep blue
    _rounded_rect(
        draw,
        (margin, margin, SIZE - margin, SIZE - margin),
        radius=48,
        fill=bg_color,
    )

    # -- Inner lighter circle --
    cx, cy = SIZE // 2, SIZE // 2
    cr = 80  # circle radius
    draw.ellipse(
        [cx - cr, cy - cr, cx + cr, cy + cr],
        fill=(255, 255, 255, 30),
    )

    # -- Play triangle --
    # Points of a right-pointing play triangle
    tx1, ty1 = cx - 24, cy - 36
    tx2, ty2 = cx - 24, cy + 36
    tx3, ty3 = cx + 40, cy
    draw.polygon([(tx1, ty1), (tx2, ty2), (tx3, ty3)], fill=(255, 255, 255, 230))

    # -- Film strip dots on right side --
    dot_radius = 6
    dot_color = (255, 255, 255, 180)
    for i in range(4):
        dy = cy - 45 + i * 30
        draw.ellipse(
            [cx + 58 - dot_radius, dy - dot_radius, cx + 58 + dot_radius, dy + dot_radius],
            fill=dot_color,
        )

    # -- Bottom label "PPT→Video" --
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    label = "PPT"
    # Use draw.text with a simple approach
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    lx = (SIZE - tw) // 2
    ly = SIZE - margin - th - 8
    # White rounded rect behind text
    text_bg_margin = 8
    _rounded_rect(
        draw,
        (lx - text_bg_margin, ly - 4, lx + tw + text_bg_margin, ly + th + 4),
        radius=12,
        fill=(255, 255, 255, 200),
    )
    # Change "PPT" to "PPT" with arrow
    draw.text((lx, ly), "PPT ▶", fill=(30, 50, 100), font=font)

    # Save as ICO (multi-res)
    # Pillow's save with format='ICO' writes the first frame; we pass sizes
    img.save(ICON_PATH, format="ICO", sizes=[(256, 256)])
    print(f"Icon saved: {ICON_PATH}")


if __name__ == "__main__":
    generate_icon()

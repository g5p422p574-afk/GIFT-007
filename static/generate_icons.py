"""Generate PWA icons for Gift app. Run once: python generate_icons.py"""
import os
from PIL import Image, ImageDraw

PRIMARY = "#8b6f5e"
OUT_DIR = os.path.join(os.path.dirname(__file__), "icons")


def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = size * 0.08
    radius = size * 0.18
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=PRIMARY,
    )

    # Center a white "G"
    text = "G"
    for font_size in range(size, 0, -1):
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            try:
                font = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", font_size)
            except OSError:
                font = ImageFont.load_default()
                break
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= size * 0.55:
            break

    draw.text(
        (size / 2, size / 2),
        text,
        fill="white",
        font=font,
        anchor="mm",
    )

    return img


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    from PIL import ImageFont
    for s in [192, 512]:
        path = os.path.join(OUT_DIR, f"icon-{s}.png")
        make_icon(s).save(path, "PNG")
        print(f"Created {path}")

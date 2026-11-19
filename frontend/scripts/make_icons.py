"""Render the PWA icons (PNG) from the Veyra radar mark. Dev tool: needs Pillow.

    ../backend/.venv/Scripts/python -m pip install pillow   (once)
    ../backend/.venv/Scripts/python scripts/make_icons.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public"
BG, PANEL, CYAN, AMBER = (4, 13, 32), (6, 18, 42), (45, 226, 230), (255, 181, 71)
S = 4  # supersample for smooth edges


def mark(size: int, scale: float, rounded: bool) -> Image.Image:
    n = size * S
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.22), fill=BG)
    else:
        d.rectangle([0, 0, n, n], fill=BG)  # maskable: full bleed, the OS applies the shape
    c, r = n / 2, n * 0.344 * scale
    d.ellipse([c - r, c - r, c + r, c + r], fill=PANEL, outline=CYAN, width=max(1, int(n * 0.039 * scale)))
    r2 = n * 0.203 * scale
    ring = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([c - r2, c - r2, c + r2, c + r2], outline=CYAN + (90,), width=max(1, int(n * 0.023 * scale)))
    img = Image.alpha_composite(img, ring)
    sweep = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sweep)
    rs = n * 0.328 * scale
    for i in range(60):  # fading radar sweep wedge from 12 o'clock to ~2 o'clock
        a0, a1 = -90 + i, -90 + i + 1.5
        sd.pieslice([c - rs, c - rs, c + rs, c + rs], a0, a1, fill=CYAN + (int(205 * i / 60),))
    img = Image.alpha_composite(img, sweep)
    d = ImageDraw.Draw(img)
    bx, by, br = c + n * 0.141 * scale, c - n * 0.180 * scale, n * 0.043 * scale
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=AMBER)
    cr = n * 0.039 * scale
    d.ellipse([c - cr, c - cr, c + cr, c + cr], fill=CYAN)
    return img.resize((size, size), Image.LANCZOS)


for size in (192, 512):
    mark(size, 1.0, True).save(OUT / f"pwa-{size}.png")
mark(512, 0.78, False).save(OUT / "pwa-maskable-512.png")  # content inside the 80% safe zone
mark(180, 0.9, False).convert("RGB").save(OUT / "apple-touch-icon.png")
mark(64, 1.0, True).save(OUT / "favicon.png")
# Android status-bar badge: white silhouette on transparent (the OS tints it)
n = 96 * S
badge = Image.new("RGBA", (n, n), (0, 0, 0, 0))
bd = ImageDraw.Draw(badge)
c = n / 2
for r, w in ((n * 0.44, int(n * 0.08)), (n * 0.26, int(n * 0.06))):
    bd.ellipse([c - r, c - r, c + r, c + r], outline=(255, 255, 255, 255), width=w)
bd.pieslice([c - n * 0.40, c - n * 0.40, c + n * 0.40, c + n * 0.40], -90, -30, fill=(255, 255, 255, 255))
bd.ellipse([c - n * 0.07, c - n * 0.07, c + n * 0.07, c + n * 0.07], fill=(255, 255, 255, 255))
badge.resize((96, 96), Image.LANCZOS).save(OUT / "badge-96.png")
print("icons written to", OUT)

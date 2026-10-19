#!/usr/bin/env python3
"""Regenerate the DavidTube header logo PNGs from davidtube/source/*.svg.

Usage: python3 -I davidtube/tools/make_logos.py
"""
import base64
import io
import os
import re

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SOURCE = os.path.join(ROOT, "source")
BUNDLE = os.path.join(ROOT, "layout", "Library", "Application Support", "DavidTube.bundle")

SOURCES = {
    "dark": "davidtube_fundo_escuro.svg",
    "light": "davidtube_fundo_claro.svg",
}

SS = 3  # supersampling factor
CANVAS = (1600, 420)
ICON_BOX = (20, 20, 380, 380)  # x, y, w, h
TEXT = "DavidTube"
TEXT_X, BASELINE, FONT_SIZE, SPACING = 430, 292, 246, -7
CROP = (28, 20, 1415, 400)  # left, top, right, bottom
HEIGHTS = {"@2x": 240, "@3x": 360}


def data_uri(svg, mime_re):
    m = re.search(r"data:(%s);base64,([A-Za-z0-9+/=\s]+)" % mime_re, svg)
    if not m:
        raise SystemExit("no embedded %s found" % mime_re)
    return base64.b64decode(re.sub(r"\s+", "", m.group(2)))


def text_fill(svg):
    m = re.search(r"<text[^>]*\sfill=\"(#[0-9A-Fa-f]{6})\"", svg)
    if not m:
        m = re.search(r"<text[^>]*>", svg)
        m = re.search(r"fill:\s*(#[0-9A-Fa-f]{6})", m.group(0)) if m else None
    if not m:
        raise SystemExit("text fill not found")
    h = m.group(1).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def compose(svg):
    icon = Image.open(io.BytesIO(data_uri(svg, r"image/png"))).convert("RGBA")
    ttf = data_uri(svg, r"(?:font|application)/[A-Za-z0-9.+-]+")
    fill = text_fill(svg)

    canvas = Image.new("RGBA", (CANVAS[0] * SS, CANVAS[1] * SS), (0, 0, 0, 0))
    bx, by, bw, bh = ICON_BOX
    scale = min(bw / icon.width, bh / icon.height)
    iw, ih = round(icon.width * scale * SS), round(icon.height * scale * SS)
    icon = icon.resize((iw, ih), Image.LANCZOS)
    canvas.alpha_composite(icon, (round((bx + bw / 2) * SS - iw / 2), round((by + bh / 2) * SS - ih / 2)))

    font = ImageFont.truetype(io.BytesIO(ttf), FONT_SIZE * SS)
    draw = ImageDraw.Draw(canvas)
    x = TEXT_X * SS
    for ch in TEXT:
        draw.text((x, BASELINE * SS), ch, font=font, fill=fill, anchor="ls")
        x += font.getlength(ch) + SPACING * SS

    l, t, r, b = CROP
    return canvas.crop((l * SS, t * SS, r * SS, b * SS))


def main():
    os.makedirs(BUNDLE, exist_ok=True)
    for variant, name in SOURCES.items():
        with open(os.path.join(SOURCE, name), encoding="utf-8") as f:
            svg = f.read()
        print(variant)
        img = compose(svg)
        for suffix, h in HEIGHTS.items():
            w = round(img.width * h / img.height)
            out = img.resize((w, h), Image.LANCZOS)
            path = os.path.join(BUNDLE, "davidtube_%s%s.png" % (variant, suffix))
            out.save(path, optimize=True)
            print("  wrote %s (%dx%d)" % (os.path.basename(path), w, h))


if __name__ == "__main__":
    main()

"""Render the DavidTube logo at arbitrary sizes as premultiplied BGRA bytes."""
import functools
import os

from PIL import Image, ImageChops

from davidtube.tools import make_logos


@functools.lru_cache(maxsize=None)
def _source(variant):
    with open(os.path.join(make_logos.SOURCE, make_logos.SOURCES[variant]), encoding="utf-8") as f:
        return make_logos.compose(f.read())


def render_logo(variant, width, height):
    """Contain-fit and center the logo on a transparent width x height canvas.

    Returns premultiplied BGRA bytes (len == width*height*4).
    """
    if variant not in make_logos.SOURCES:
        raise ValueError("unknown variant: %r" % (variant,))
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    src = _source(variant)
    scale = min(width / src.width, height / src.height)
    w = max(1, min(width, round(src.width * scale)))
    h = max(1, min(height, round(src.height * scale)))
    # Resize in premultiplied space to avoid dark fringes at the edges.
    logo = src.convert("RGBa").resize((w, h), Image.LANCZOS)
    canvas = Image.new("RGBa", (width, height), (0, 0, 0, 0))
    canvas.paste(logo, ((width - w) // 2, (height - h) // 2))
    # Pillow's "RGBa" is premultiplied RGBA; emit it as B,G,R,A.
    r, g, b, a = canvas.split()
    # LANCZOS ringing can push a channel above alpha; clamp to stay valid.
    b, g, r = (ImageChops.darker(c, a) for c in (b, g, r))
    return Image.merge("RGBA", (b, g, r, a)).tobytes()

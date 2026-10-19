import os
import unittest

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.join(HERE, "..", "layout", "Library", "Application Support", "DavidTube.bundle")
HEIGHTS = {"@2x": 240, "@3x": 360}


def load(name):
    return Image.open(os.path.join(BUNDLE, name))


def opaque_pixels(img, text_only=False):
    """Opaque pixels; text_only skips the avatar area (left 30%), which has its own white."""
    x0 = int(img.width * 0.30) if text_only else 0
    return [img.getpixel((x, y)) for y in range(img.height) for x in range(x0, img.width)
            if img.getpixel((x, y))[3] == 255]


class TestLogoAssets(unittest.TestCase):
    def test_all_files(self):
        for variant in ("dark", "light"):
            for suffix, height in HEIGHTS.items():
                name = "davidtube_%s%s.png" % (variant, suffix)
                with self.subTest(name=name):
                    path = os.path.join(BUNDLE, name)
                    self.assertTrue(os.path.exists(path))
                    img = load(name)
                    self.assertEqual(img.mode, "RGBA")
                    self.assertEqual(img.getpixel((0, 0))[3], 0)
                    ratio = img.width / img.height
                    self.assertTrue(3.55 <= ratio <= 3.75, ratio)
                    self.assertEqual(img.height, height)

    def test_dark_has_white(self):
        for suffix in HEIGHTS:
            img = load("davidtube_dark%s.png" % suffix)
            self.assertTrue(any(p[:3] == (255, 255, 255) for p in opaque_pixels(img, text_only=True)))

    def test_light_has_near_111_and_no_white(self):
        for suffix in HEIGHTS:
            img = load("davidtube_light%s.png" % suffix)
            px = opaque_pixels(img, text_only=True)
            self.assertFalse(any(p[:3] == (255, 255, 255) for p in px))
            self.assertTrue(any(all(abs(c - 17) <= 3 for c in p[:3]) for p in px))


if __name__ == "__main__":
    unittest.main()

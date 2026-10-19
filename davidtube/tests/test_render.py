import unittest

from davidtube.tools import render

SIZES = [(122, 48), (244, 96), (366, 144), (129, 48), (258, 96), (387, 144)]
LOGO_ASPECT = 3.65


def pixels(buf, w, h):
    return [tuple(buf[i * 4:i * 4 + 4]) for i in range(w * h)]


def bbox(buf, w, h, thresh=0):
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            if buf[(y * w + x) * 4 + 3] > thresh:
                xs.append(x)
                ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


class RenderLogoTest(unittest.TestCase):
    def test_length_and_corner_alpha(self):
        for variant in ("dark", "light"):
            for w, h in SIZES:
                with self.subTest(variant=variant, w=w, h=h):
                    buf = render.render_logo(variant, w, h)
                    self.assertIsInstance(buf, bytes)
                    self.assertEqual(len(buf), w * h * 4)
                    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
                        self.assertEqual(buf[(y * w + x) * 4 + 3], 0)

    def test_premultiplied(self):
        for variant in ("dark", "light"):
            for w, h in SIZES:
                with self.subTest(variant=variant, w=w, h=h):
                    buf = render.render_logo(variant, w, h)
                    for i in range(0, len(buf), 4):
                        a = buf[i + 3]
                        self.assertLessEqual(max(buf[i:i + 3]), a)

    def test_bbox_fit_centered_aspect(self):
        for w, h in SIZES:
            with self.subTest(w=w, h=h):
                buf = render.render_logo("dark", w, h)
                x0, y0, x1, y1 = bbox(buf, w, h)
                self.assertGreaterEqual(x0, 0)
                self.assertGreaterEqual(y0, 0)
                self.assertLess(x1, w)
                self.assertLess(y1, h)
                # Centering is within 1px of ideal; allow 2px because the
                # logo's own transparent margins and antialiased edge pixels
                # make exact centering impossible.
                self.assertLessEqual(abs(x0 - (w - 1 - x1)), 2)
                self.assertLessEqual(abs(y0 - (h - 1 - y1)), 2)
        for w, h in ((244, 96), (366, 144)):
            with self.subTest(aspect=(w, h)):
                buf = render.render_logo("dark", w, h)
                x0, y0, x1, y1 = bbox(buf, w, h)
                aspect = (x1 - x0 + 1) / (y1 - y0 + 1)
                self.assertAlmostEqual(aspect / LOGO_ASPECT, 1.0, delta=0.02)

    def test_text_color(self):
        w, h = 366, 144
        for variant, want in (("dark", 255), ("light", 17)):
            with self.subTest(variant=variant):
                buf = render.render_logo(variant, w, h)
                x0, y0, x1, y1 = bbox(buf, w, h)
                start = x0 + int((x1 - x0 + 1) * 0.3)
                opaque = 0
                for y in range(y0, y1 + 1):
                    for x in range(start, x1 + 1):
                        b, g, r, a = buf[(y * w + x) * 4:(y * w + x) * 4 + 4]
                        if a == 255:
                            opaque += 1
                            for c in (b, g, r):
                                self.assertAlmostEqual(c, want, delta=2)
                self.assertGreater(opaque, 500)

    def test_byte_order_bgra(self):
        w, h = 366, 144
        buf = render.render_logo("dark", w, h)
        x0, y0, x1, y1 = bbox(buf, w, h)
        # The avatar (with the red YouTube-style icon) is the left ~27% of the logo.
        limit = x0 + int((x1 - x0 + 1) * 0.27)
        reddish = 0
        for y in range(y0, y1 + 1):
            for x in range(x0, limit):
                b, g, r, a = buf[(y * w + x) * 4:(y * w + x) * 4 + 4]
                if a == 255 and r > 150 and r > b + 80 and r > g + 80:
                    reddish += 1
        self.assertGreater(reddish, 20)

    def test_invalid_args(self):
        with self.assertRaises(ValueError):
            render.render_logo("blue", 10, 10)
        for w, h in ((0, 10), (10, 0), (-1, 10), (10, -5)):
            with self.assertRaises(ValueError):
                render.render_logo("dark", w, h)


if __name__ == "__main__":
    unittest.main()

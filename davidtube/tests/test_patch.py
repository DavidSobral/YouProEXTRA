import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from davidtube.tests.fixtures import (CAR_PATH, IDENT, LOGO_FACETS, SCALE, STANDALONE,
                                      build_catalog, link_catalog, link_catalog_parts,
                                      logo_rendition_name, logo_size, make_csi, make_link_csi,
                                      write_ipa)
from davidtube.tools import patch_car
from davidtube.tools.car import Car, CarError
from davidtube.tools.csi import decode_image_payload, parse_csi_header
from davidtube.tools.patch_car import TARGETS, patch_catalog, patch_ipa, variant_for
from davidtube.tools.render import render_logo

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SCRIPT = os.path.join(ROOT, "davidtube", "tools", "patch_car.py")


def target_blocks(car):
    """{(facet, scale): value_block} for the logo facets."""
    ids = {a[IDENT]: n for n, a in car.facets().items() if n in TARGETS}
    return {(ids[r.attrs[IDENT]], r.attrs[SCALE]): r.value_block
            for r in car.renditions() if r.attrs[IDENT] in ids}


class VariantTests(unittest.TestCase):
    def test_targets(self):
        self.assertEqual(TARGETS, LOGO_FACETS)

    def test_variant_for(self):
        expected = {"youtube_logo": "light", "youtube_logo_dark": "dark",
                    "youtube_logo_cairo": "light", "youtube_logo_dark_cairo": "dark",
                    "youtube_premium_logo": "light", "youtube_premium_logo_white": "dark",
                    "youtube_premium_logo_cairo": "light",
                    "youtube_premium_logo_dark_cairo": "dark"}
        self.assertEqual({n: variant_for(n) for n in TARGETS}, expected)


class PatchCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = link_catalog()
        cls.out = patch_catalog(cls.data)

    def test_targets_replaced_by_standalone_images(self):
        old, new = Car(self.data), Car(self.out)
        blocks = target_blocks(old)
        self.assertEqual(len(blocks), 24)
        for (facet, scale), b in blocks.items():
            oh = parse_csi_header(old.block(b))
            if (facet, scale) not in STANDALONE:
                self.assertEqual(oh.payload_kind, b"INLK")
            csi = new.block(b)
            hd = parse_csi_header(csi)
            w, h = logo_size(facet, scale)
            self.assertEqual((hd.payload_kind, hd.layout, hd.pixel_format),
                             (b"CELM", 12, b"BGRA"))
            self.assertEqual((hd.width, hd.height, hd.scale100, hd.name),
                             (w, h, 100 * scale, logo_rendition_name(facet, scale)))
            self.assertEqual(decode_image_payload(csi), render_logo(variant_for(facet), w, h))

    def test_other_blocks_untouched(self):
        old, new = Car(self.data), Car(self.out)
        self.assertEqual(new.block_count(), old.block_count())
        changed = set(target_blocks(old).values())
        for i in range(old.block_count()):
            if i not in changed:
                self.assertEqual(new.block(i), old.block(i), "block %d" % i)
        self.assertEqual(new.facets(), old.facets())
        self.assertEqual(new.renditions(), old.renditions())
        self.assertEqual(self.out[:len(self.data)][:32], self.data[:32])

    def test_idempotent(self):
        twice = patch_catalog(self.out)
        a, b = Car(self.out), Car(twice)
        self.assertEqual(b.block_count(), a.block_count())
        for i in range(a.block_count()):
            self.assertEqual(b.block(i), a.block(i), "block %d" % i)

    def test_missing_facet(self):
        facets, rends = link_catalog_parts()
        facets = [f for f in facets if f[0] != "youtube_premium_logo_cairo"]
        with self.assertRaisesRegex(CarError, "youtube_premium_logo_cairo"):
            patch_catalog(build_catalog(facets, rends))

    def test_facet_without_renditions(self):
        facets, rends = link_catalog_parts()
        ident = dict(facets)["youtube_logo_dark"][IDENT]
        rends = [r for r in rends if r[0][IDENT] != ident]
        with self.assertRaisesRegex(CarError, "youtube_logo_dark"):
            patch_catalog(build_catalog(facets, rends))

    def test_wrong_scale_sets(self):
        facets, rends = link_catalog_parts()
        ident = dict(facets)["youtube_logo"][IDENT]
        two = [r for r in rends if not (r[0][IDENT] == ident and r[0][SCALE] == 3)]
        extra = rends + [({IDENT: ident, SCALE: 2, 15: 1}, make_link_csi(20, 8, 200))]
        for bad in (two, extra):
            with self.assertRaisesRegex(CarError, "youtube_logo"):
                patch_catalog(build_catalog(facets, bad))

    def test_header_scale_disagrees_with_key(self):
        facets, rends = link_catalog_parts()
        ident = dict(facets)["youtube_logo"][IDENT]
        rends = [(a, make_link_csi(20, 8, 300)) if a[IDENT] == ident and a[SCALE] == 2
                 else (a, v) for a, v in rends]
        with self.assertRaises(CarError):
            patch_catalog(build_catalog(facets, rends))

    def test_non_bgra_target(self):
        facets, rends = link_catalog_parts()
        ident = dict(facets)["youtube_logo"][IDENT]
        rends = [(a, make_csi(20, 8, 200, pixel_format=b" 8AG")) if a[IDENT] == ident
                 and a[SCALE] == 2 else (a, v) for a, v in rends]
        with self.assertRaises(CarError):
            patch_catalog(build_catalog(facets, rends))

    def test_no_template(self):
        facets, rends = link_catalog_parts()
        rends = [(a, v) for a, v in rends if a[IDENT] != 7]
        rends = [(a, make_link_csi(*logo_size("x", a[SCALE]), 100 * a[SCALE]))
                 if a[IDENT] >= 1000 else (a, v) for a, v in rends]
        with self.assertRaises(CarError):
            patch_catalog(build_catalog(facets, rends))

    def test_garbage(self):
        for bad in (b"", b"not a catalog", self.data[:200]):
            with self.assertRaises(CarError):
                patch_catalog(bad)

    def test_partial_failure_raises(self):
        real = patch_car.build_image_csi
        calls = []

        def flaky(template, name, w, h, s, bgra):
            calls.append(name)
            if len(calls) == 23:  # one wrong pixel in rendition 23 of 24
                bgra = bytes([bgra[0] ^ 1]) + bgra[1:]
            return real(template, name, w, h, s, bgra)

        with mock.patch.object(patch_car, "build_image_csi", flaky):
            with self.assertRaisesRegex(CarError, "pixels"):
                patch_catalog(self.data)
        self.assertEqual(len(calls), 24)

    def test_wrong_name_detected(self):
        real = patch_car.build_image_csi
        with mock.patch.object(patch_car, "build_image_csi",
                               lambda t, n, *a: real(t, n + "x", *a)):
            with self.assertRaises(CarError):
                patch_catalog(self.data)

    def test_collateral_damage_detected(self):
        real = Car.to_bytes
        victim = Car(self.data).renditions()[-1].value_block  # a non-target block
        self.assertNotIn(victim, target_blocks(Car(self.data)).values())

        def corrupt(car):
            buf = bytearray(real(car))
            addr = int.from_bytes(self.data[16:20], "big")  # index table offset
            off = int.from_bytes(self.data[addr + 4 + 8 * victim:addr + 8 + 8 * victim], "big")
            buf[off + 50] ^= 0xFF
            return bytes(buf)

        with mock.patch.object(Car, "to_bytes", corrupt):
            with self.assertRaises(CarError):
                patch_catalog(self.data)


class PatchIpaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.car = link_catalog()
        cls.patched = patch_catalog(cls.car)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "in.ipa")
        self.dst = os.path.join(self.tmp.name, "out.ipa")

    def tearDown(self):
        self.tmp.cleanup()

    def run_patch(self, src=None, dst=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = patch_ipa(src or self.src, dst or self.dst)
        return ok, buf.getvalue()

    def assert_patched(self, car_path=CAR_PATH):
        with zipfile.ZipFile(self.src) as a, zipfile.ZipFile(self.dst) as b:
            ia, ib = a.infolist(), b.infolist()
            self.assertEqual([i.filename for i in ib], [i.filename for i in ia])
            for x, y in zip(ia, ib):
                self.assertEqual((y.compress_type, y.date_time, y.external_attr, y.create_system),
                                 (x.compress_type, x.date_time, x.external_attr, x.create_system),
                                 x.filename)
                if x.filename == car_path:
                    self.assertEqual(b.read(y), self.patched)
                else:
                    self.assertEqual(b.read(y), a.read(x), x.filename)
            self.assertIsNone(b.testzip())

    def assert_untouched(self, ok, out):
        self.assertFalse(ok)
        self.assertIn("::warning::DavidTube logo: ", out)
        self.assertEqual(out.count("\n"), 1)
        with open(self.src, "rb") as a, open(self.dst, "rb") as b:
            self.assertEqual(b.read(), a.read())

    def test_good_ipa_deflated_car(self):
        write_ipa(self.src, self.car)
        ok, out = self.run_patch()
        self.assertTrue(ok)
        self.assertNotIn("::warning::", out)
        self.assert_patched()

    def test_good_ipa_stored_car(self):
        write_ipa(self.src, self.car, car_compress=zipfile.ZIP_STORED)
        self.assertTrue(self.run_patch()[0])
        self.assert_patched()

    def test_other_app_name(self):
        write_ipa(self.src, self.car, app="YouTubeX.app")
        self.assertTrue(self.run_patch()[0])
        self.assert_patched(CAR_PATH.replace("YouTube.app", "YouTubeX.app"))

    def test_two_candidate_apps(self):
        write_ipa(self.src, self.car, app="A.app")
        with zipfile.ZipFile(self.src, "a") as z:
            z.writestr("Payload/B.app/Innertube_Resources.bundle/Assets.car", self.car)
        self.assert_untouched(*self.run_patch())

    def test_without_catalog(self):
        write_ipa(self.src, None)
        self.assert_untouched(*self.run_patch())

    def test_corrupt_catalog(self):
        write_ipa(self.src, b"BOMStore" + b"\xff" * 64)
        self.assert_untouched(*self.run_patch())

    def test_missing_facet(self):
        facets, rends = link_catalog_parts()
        write_ipa(self.src, build_catalog([f for f in facets if f[0] != "youtube_logo"], rends))
        ok, out = self.run_patch()
        self.assert_untouched(ok, out)
        self.assertIn("youtube_logo", out)

    def test_not_a_zip(self):
        with open(self.src, "wb") as f:
            f.write(b"PK not really a zip")
        self.assert_untouched(*self.run_patch())

    def test_unexpected_exception(self):
        write_ipa(self.src, self.car)
        with mock.patch.object(patch_car, "render_logo", side_effect=MemoryError("boom")):
            ok, out = self.run_patch()
        self.assert_untouched(ok, out)
        self.assertIn("boom", out)

    def test_missing_input_never_raises(self):
        ok, out = self.run_patch(src=os.path.join(self.tmp.name, "nope.ipa"))
        self.assertFalse(ok)
        self.assertIn("::warning::DavidTube logo: ", out)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_no_temp_files_left(self):
        write_ipa(self.src, None)
        self.run_patch()
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["in.ipa", "out.ipa"])
        write_ipa(self.src, self.car)
        self.run_patch()
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["in.ipa", "out.ipa"])

    def test_in_place(self):
        write_ipa(self.src, self.car)
        with open(self.src, "rb") as f:
            original = f.read()
        ok, _ = self.run_patch(self.src, self.src)
        self.assertTrue(ok)
        with zipfile.ZipFile(self.src) as z:
            self.assertEqual(z.read(CAR_PATH), self.patched)
        with open(self.src, "wb") as f:
            f.write(original[:-30])  # truncated zip: fallback must leave it as is
        ok, out = self.run_patch(self.src, self.src)
        self.assertFalse(ok)
        with open(self.src, "rb") as f:
            self.assertEqual(f.read(), original[:-30])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True,
                              text=True, cwd=tempfile.gettempdir())

    def test_patches(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "in.ipa"), os.path.join(d, "out.ipa")
            write_ipa(src, link_catalog())
            r = self.run_cli(src, dst)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertNotIn("::warning::", r.stdout)
            with zipfile.ZipFile(dst) as z:
                self.assertEqual(z.read(CAR_PATH), patch_catalog(link_catalog()))

    def test_fallback_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "in.ipa"), os.path.join(d, "out.ipa")
            write_ipa(src, None)
            r = self.run_cli(src, dst)
            self.assertEqual(r.returncode, 0)
            self.assertIn("::warning::DavidTube logo: ", r.stdout)
            with open(src, "rb") as a, open(dst, "rb") as b:
                self.assertEqual(a.read(), b.read())

    def test_usage(self):
        for args in ((), ("only-one",), ("a", "b", "c")):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 2)
            self.assertIn("usage", r.stderr.lower())


REAL_TARGETS = {  # facet: 1x size
    "youtube_logo": (122, 48), "youtube_logo_dark": (122, 48), "youtube_logo_cairo": (122, 48),
    "youtube_logo_dark_cairo": (122, 48), "youtube_premium_logo": (129, 48),
    "youtube_premium_logo_white": (129, 48), "youtube_premium_logo_cairo": (129, 48),
    "youtube_premium_logo_dark_cairo": (129, 48)}


@unittest.skipUnless(os.environ.get("DAVIDTUBE_REAL_IPA"), "set DAVIDTUBE_REAL_IPA")
class RealIpaTest(unittest.TestCase):
    def test_real_ipa(self):
        src = os.environ["DAVIDTUBE_REAL_IPA"]
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "out.ipa")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = patch_ipa(src, dst)
            self.assertEqual(buf.getvalue(), "")
            self.assertTrue(ok)
            with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
                ia, ib = a.infolist(), b.infolist()
                self.assertEqual([i.filename for i in ib], [i.filename for i in ia])
                for x, y in zip(ia, ib):
                    self.assertEqual((y.compress_type, y.date_time, y.external_attr),
                                     (x.compress_type, x.date_time, x.external_attr))
                    if x.filename != CAR_PATH:
                        self.assertEqual((y.CRC, y.file_size), (x.CRC, x.file_size), x.filename)
                        self.assertEqual(b.read(y), a.read(x), x.filename)
                old_data, new_data = a.read(CAR_PATH), b.read(CAR_PATH)
        old, new = Car(old_data), Car(new_data)
        self.assertEqual(len(new.facets()), 612)
        self.assertEqual(new.facets(), old.facets())
        self.assertEqual(new.renditions(), old.renditions())
        self.assertEqual(new.block_count(), old.block_count())
        blocks = target_blocks(old)
        self.assertEqual(sorted({f for f, _ in blocks}), sorted(REAL_TARGETS))
        self.assertEqual(sorted({s for _, s in blocks}), [1, 2, 3])
        changed = {i for i in range(old.block_count()) if old.block(i) != new.block(i)}
        self.assertEqual(changed, set(blocks.values()))
        self.assertEqual(len(changed), 24)
        for (facet, scale), i in blocks.items():
            oh, nh = parse_csi_header(old.block(i)), parse_csi_header(new.block(i))
            w, h = REAL_TARGETS[facet]
            self.assertEqual((oh.width, oh.height, oh.scale100), (w * scale, h * scale, 100 * scale))
            self.assertEqual((nh.width, nh.height, nh.scale100, nh.name),
                             (oh.width, oh.height, oh.scale100, oh.name))
            self.assertEqual((nh.payload_kind, nh.layout, nh.pixel_format), (b"CELM", 12, b"BGRA"))
            self.assertEqual(decode_image_payload(new.block(i)),
                             render_logo(variant_for(facet), nh.width, nh.height))


if __name__ == "__main__":
    unittest.main()

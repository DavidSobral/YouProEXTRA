import json
import os
import subprocess
import sys
import tempfile
import unittest

from davidtube.tests.helpers import ROOT, full_listing, make_fake_assetutil
from davidtube.tools import validate_car
from davidtube.tools.patch_car import TARGETS
from davidtube.tools.validate_car import compare_listings

SCRIPT = os.path.join(ROOT, "davidtube", "tools", "validate_car.py")
T = {"youtube_logo"}


def e(name, scale=2, w=10, h=4, **kw):
    d = {"Name": name, "Scale": scale, "PixelWidth": w, "PixelHeight": h, "SizeOnDisk": 100}
    d.update(kw)
    return d


HEADER = {"AssetType": "Header", "Version": 7}
BASE = [HEADER, e("youtube_logo", 1), e("youtube_logo", 2, 20, 8), e("ic_x", 3, 6, 6)]


def cp(x):
    return json.loads(json.dumps(x))


class CompareTests(unittest.TestCase):
    def test_empty_listing_is_a_difference(self):
        self.assertTrue(compare_listings([], [], T))

    def test_header_only_listing_is_a_difference(self):
        self.assertTrue(compare_listings([HEADER], [HEADER], T))

    def test_missing_target_facet_named(self):
        full = full_listing()
        o = [x for x in full if x.get("Name") != "youtube_premium_logo"]
        d = compare_listings(o, o, set(TARGETS))
        self.assertTrue(any("youtube_premium_logo" in x for x in d), d)
        self.assertFalse(any("youtube_logo_dark" in x for x in d), d)

    def test_patched_missing_target_named(self):
        full = full_listing()
        p = [x for x in full if x.get("Name") != "youtube_logo_cairo"]
        d = compare_listings(full, p, set(TARGETS))
        self.assertTrue(any("youtube_logo_cairo" in x for x in d), d)

    def test_two_scales_only_is_a_difference(self):
        full = full_listing()
        o = [x for x in full if not (x.get("Name") == "youtube_logo" and x["Scale"] == 3)]
        d = compare_listings(o, o, set(TARGETS))
        self.assertTrue(any("youtube_logo" in x and "scale" in x for x in d), d)

    def test_full_real_listing_ok(self):
        self.assertEqual(compare_listings(full_listing(), full_listing(), set(TARGETS)), [])

    def test_identical(self):
        self.assertEqual(compare_listings(BASE, cp(BASE), T), [])

    def test_changed_target_allowed(self):
        p = cp(BASE)
        p[2]["SizeOnDisk"] = 999
        p[2]["Encoding"] = "ARGB"
        self.assertEqual(compare_listings(BASE, p, T), [])

    def test_png_suffix_variants(self):
        p = cp(BASE)
        p[1]["Name"] = "youtube_logo.png"
        self.assertEqual(compare_listings(BASE, p, T), [])
        o = cp(BASE)
        o[2]["Name"] = "youtube_logo.png"
        self.assertEqual(compare_listings(o, BASE, T), [])

    def test_target_missing(self):
        p = cp(BASE)
        del p[2]
        d = compare_listings(BASE, p, T)
        self.assertTrue(d)
        self.assertIn("youtube_logo", " ".join(d))

    def test_target_different_width(self):
        p = cp(BASE)
        p[2]["PixelWidth"] = 21
        d = compare_listings(BASE, p, T)
        self.assertTrue(d)
        self.assertIn("youtube_logo", " ".join(d))

    def test_target_different_scale(self):
        p = cp(BASE)
        p[2]["Scale"] = 3
        self.assertTrue(compare_listings(BASE, p, T))

    def test_target_added(self):
        p = cp(BASE) + [e("youtube_logo", 3, 30, 12)]
        self.assertTrue(compare_listings(BASE, p, T))

    def test_changed_nontarget(self):
        p = cp(BASE)
        p[3]["SizeOnDisk"] = 1
        d = compare_listings(BASE, p, T)
        self.assertTrue(d)
        self.assertIn("ic_x", " ".join(d))

    def test_removed_entry(self):
        d = compare_listings(BASE, BASE[:3], T)
        self.assertTrue(d)
        self.assertIn("ic_x", " ".join(d))

    def test_added_entry(self):
        d = compare_listings(BASE, cp(BASE) + [e("new_thing")], T)
        self.assertTrue(d)
        self.assertIn("new_thing", " ".join(d))

    def test_header_changed(self):
        p = cp(BASE)
        p[0]["Version"] = 8
        self.assertTrue(compare_listings(BASE, p, T))

    def test_header_removed(self):
        self.assertTrue(compare_listings(BASE, BASE[1:], T))

    def test_duplicate_names_multiset(self):
        o = BASE + [e("ic_x", 3, 6, 6, Idiom="phone")]
        self.assertEqual(compare_listings(o, list(reversed(cp(o))), T), [])
        p = cp(o)
        p[-1]["Idiom"] = "pad"
        self.assertTrue(compare_listings(o, p, T))

    def test_order_irrelevant(self):
        self.assertEqual(compare_listings(BASE, list(reversed(cp(BASE))), T), [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = os.path.join(self.tmp.name, "bin")
        os.mkdir(self.bin)
        self.a = os.path.join(self.tmp.name, "a.car")
        self.b = os.path.join(self.tmp.name, "b.car")
        for p in (self.a, self.b):
            with open(p, "wb") as f:
                f.write(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, path=None):
        env = dict(os.environ)
        env["PATH"] = path if path is not None else self.bin + os.pathsep + env["PATH"]
        return subprocess.run([sys.executable, "-I", SCRIPT] + list(args), env=env,
                              capture_output=True, text=True)

    def fake(self, listing_a, listing_b):
        body = ('#!/bin/sh\ncase "$2" in\n*/a.car) cat <<\'EOF\'\n%s\nEOF\n;;\n'
                '*) cat <<\'EOF\'\n%s\nEOF\n;;\nesac\n') % (json.dumps(listing_a), json.dumps(listing_b))
        make_fake_assetutil(self.bin, body)

    def test_ok(self):
        base = full_listing()
        p = cp(base)
        p[1]["SizeOnDisk"] = 5
        self.fake(base, p)
        r = self.run_cli(self.a, self.b)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "OK"))

    def test_differences_exit_1(self):
        base = full_listing()
        p = cp(base)
        p[-1]["SizeOnDisk"] = 5
        self.fake(base, p)
        r = self.run_cli(self.a, self.b)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ic_x", r.stdout)

    def test_empty_listing_exit_1(self):
        self.fake([], [])
        r = self.run_cli(self.a, self.b)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no entry for youtube_logo", r.stdout)

    def test_header_only_exit_1(self):
        self.fake([HEADER], [HEADER])
        self.assertEqual(self.run_cli(self.a, self.b).returncode, 1)

    def test_garbage_exit_1(self):
        make_fake_assetutil(self.bin, "#!/bin/sh\necho 'not json at all'\n")
        self.assertEqual(self.run_cli(self.a, self.b).returncode, 1)

    def test_assetutil_failing_exit_1(self):
        make_fake_assetutil(self.bin, "#!/bin/sh\necho '[]'\nexit 4\n")
        self.assertEqual(self.run_cli(self.a, self.b).returncode, 1)

    def test_leading_warning_line_tolerated(self):
        body = '#!/bin/sh\necho "warning: something"\ncat <<\'EOF\'\n%s\nEOF\n' % json.dumps(full_listing())
        make_fake_assetutil(self.bin, body)
        r = self.run_cli(self.a, self.b)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "OK"))

    def test_not_a_list_exit_1(self):
        make_fake_assetutil(self.bin, "#!/bin/sh\necho '{}'\n")
        self.assertEqual(self.run_cli(self.a, self.b).returncode, 1)

    def test_missing_assetutil_exit_3(self):
        r = self.run_cli(self.a, self.b, path=self.bin)  # bin has no assetutil
        self.assertEqual(r.returncode, 3)

    def test_usage(self):
        self.assertEqual(self.run_cli(self.a).returncode, 2)


if __name__ == "__main__":
    unittest.main()

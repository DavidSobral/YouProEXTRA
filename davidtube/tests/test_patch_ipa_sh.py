import os
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

from davidtube.tests.fixtures import CAR_PATH, link_catalog, write_ipa
from davidtube.tests.helpers import ROOT, make_fake_assetutil
from davidtube.tools.car import Car
from davidtube.tools.csi import parse_csi_header

SH = os.path.join(ROOT, "davidtube", "patch_ipa.sh")


def car_of(ipa):
    with zipfile.ZipFile(ipa) as z:
        return z.read(CAR_PATH)


def read(p):
    with open(p, "rb") as f:
        return f.read()


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.bin = os.path.join(t, "bin")
        os.mkdir(self.bin)
        self.ipa = os.path.join(t, "youtube.ipa")
        write_ipa(self.ipa, link_catalog())
        os.chmod(self.ipa, 0o640)
        self.orig = read(self.ipa)

    def tearDown(self):
        self.tmp.cleanup()

    def run_sh(self, ipa=None, with_assetutil=True):
        env = dict(os.environ)
        env["DAVIDTUBE_PYTHON"] = sys.executable
        env["RUNNER_TEMP"] = self.tmp.name
        # a PATH with only the basic tools; assetutil only if provided
        env["PATH"] = (self.bin + os.pathsep if with_assetutil else "") + "/usr/bin:/bin"
        return subprocess.run(["sh", SH, ipa or self.ipa], env=env, capture_output=True,
                              text=True, cwd=self.tmp.name)

    def leftovers(self):
        return sorted(n for n in os.listdir(self.tmp.name)
                      if n not in ("bin", "youtube.ipa"))

    def test_success_replaces_ipa(self):
        make_fake_assetutil(self.bin)
        r = self.run_sh()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::notice::DavidTube logo patched into IPA", r.stdout)
        self.assertNotEqual(read(self.ipa), self.orig)
        self.assertNotEqual(car_of(self.ipa), link_catalog())
        names = {n: a for n, a in Car(car_of(self.ipa)).facets().items()}
        self.assertIn("youtube_logo", names)
        self.assertEqual(stat.S_IMODE(os.stat(self.ipa).st_mode), 0o640)
        self.assertEqual(self.leftovers(), [])

    def test_assetutil_missing_keeps_ipa(self):
        r = self.run_sh(with_assetutil=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::notice::DavidTube logo: assetutil unavailable, logo not applied", r.stdout)
        self.assertEqual(read(self.ipa), self.orig)
        self.assertEqual(self.leftovers(), [])

    def test_differing_nontarget_keeps_ipa(self):
        # report an extra entry only for the patched catalog (it is bigger than the original)
        extra = ('if len(sys.argv[2]) and __import__("os").path.getsize(sys.argv[2]) '
                 '> %d: out.append({"Name": "intruder", "Scale": 1})' % len(self.orig_car()))
        make_fake_assetutil(self.bin, lister_extra=extra)
        r = self.run_sh()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning::", r.stdout)
        self.assertIn("intruder", r.stdout)
        self.assertEqual(read(self.ipa), self.orig)
        self.assertEqual(self.leftovers(), [])

    def orig_car(self):
        return link_catalog()

    def test_assetutil_failing_keeps_ipa(self):
        make_fake_assetutil(self.bin, "#!/bin/sh\necho garbage\n")
        r = self.run_sh()
        self.assertEqual(r.returncode, 0)
        self.assertIn("::warning::", r.stdout)
        self.assertEqual(read(self.ipa), self.orig)

    def test_not_a_zip_keeps_file(self):
        with open(self.ipa, "wb") as f:
            f.write(b"this is not a zip")
        make_fake_assetutil(self.bin)
        r = self.run_sh()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning::", r.stdout)
        self.assertEqual(read(self.ipa), b"this is not a zip")

    def test_ipa_without_catalog_keeps_ipa(self):
        write_ipa(self.ipa, None)
        before = read(self.ipa)
        make_fake_assetutil(self.bin)
        r = self.run_sh()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(read(self.ipa), before)

    def test_missing_argument_and_file(self):
        r = subprocess.run(["sh", SH], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        r = self.run_sh(os.path.join(self.tmp.name, "nope.ipa"))
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()

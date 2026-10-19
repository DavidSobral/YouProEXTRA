import os
import subprocess
import sys
import tempfile
import unittest

from davidtube.tests.fixtures import link_catalog, write_ipa
from davidtube.tests.helpers import ROOT, make_fake_assetutil
from davidtube.tools.patch_car import TARGETS

SH = os.path.join(ROOT, "davidtube", "mac_check.sh")


def read(p):
    with open(p, "rb") as f:
        return f.read()


class MacCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.bin = os.path.join(t, "bin")
        os.mkdir(self.bin)
        self.ipa = os.path.join(t, "youtube.ipa")
        write_ipa(self.ipa, link_catalog())
        self.orig = read(self.ipa)
        self.out = os.path.join(t, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def run_sh(self, with_assetutil=True, args=None):
        env = dict(os.environ, DAVIDTUBE_PYTHON=sys.executable, RUNNER_TEMP=self.tmp.name)
        env["PATH"] = (self.bin + os.pathsep if with_assetutil else "") + "/usr/bin:/bin"
        args = args if args is not None else [self.ipa, self.out]
        return subprocess.run(["sh", SH] + args, env=env, capture_output=True, text=True,
                              cwd=self.tmp.name)

    def test_summary(self):
        make_fake_assetutil(self.bin)
        r = self.run_sh()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name in TARGETS:
            self.assertIn(name, r.stdout)
        self.assertIn("original.json", r.stdout)
        self.assertIn("patched.json", r.stdout)
        self.assertIn("PixelWidth", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertEqual(read(self.ipa), self.orig)
        self.assertNotEqual(read(os.path.join(self.out, "work.ipa")), self.orig)
        for n in ("original.json", "patched.json", "original.car", "patched.car"):
            self.assertTrue(os.path.exists(os.path.join(self.out, n)), n)

    def test_assetutil_missing(self):
        r = self.run_sh(with_assetutil=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("assetutil", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertEqual(read(self.ipa), self.orig)

    def test_tolerates_leading_garbage_line(self):
        make_fake_assetutil(self.bin, "#!/bin/sh\necho 'warning: something'\n"
                            'echo \'[{"Name": "youtube_logo", "Scale": 2}]\'\n')
        r = self.run_sh()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("youtube_logo", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_bad_usage(self):
        r = self.run_sh(args=[])
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()

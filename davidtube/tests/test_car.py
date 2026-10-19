import os
import struct
import unittest

from davidtube.tests.fixtures import IDENT, SCALE, sample_catalog
from davidtube.tools.car import Car, CarError

TARGETS = ["youtube_logo", "youtube_logo_dark", "youtube_logo_cairo",
           "youtube_logo_dark_cairo", "youtube_premium_logo",
           "youtube_premium_logo_white", "youtube_premium_logo_cairo",
           "youtube_premium_logo_dark_cairo"]


class CarTests(unittest.TestCase):
    def setUp(self):
        self.data, self.facets, self.rends = sample_catalog()
        self.car = Car(self.data)

    def test_facets(self):
        f = self.car.facets()
        self.assertEqual(set(f), {"alpha", "beta", "gamma"})
        self.assertEqual(f["beta"][IDENT], 200)

    def test_renditions_include_forward_linked_leaves(self):
        r = self.car.renditions()
        self.assertEqual(len(r), 5)
        got = sorted((x.attrs[IDENT], x.attrs[SCALE]) for x in r)
        self.assertEqual(got, [(100, 1), (100, 2), (200, 2), (300, 1), (300, 3)])
        last = [x for x in r if x.attrs[IDENT] == 300 and x.attrs[SCALE] == 3][0]
        self.assertTrue(self.car.block(last.value_block).endswith(b"c3"))

    def test_roundtrip_identical(self):
        self.assertEqual(self.car.to_bytes(), self.data)

    def test_replace_block(self):
        r = self.car.renditions()[1]
        before = [self.car.block(i) for i in range(self.car.block_count())]
        n = self.car.block_count()
        self.car.replace_block(r.value_block, b"NEW-DATA" * 10)
        car2 = Car(self.car.to_bytes())
        self.assertEqual(car2.block_count(), n)
        self.assertEqual(car2.block(r.value_block), b"NEW-DATA" * 10)
        for i in range(n):
            if i != r.value_block:
                self.assertEqual(car2.block(i), before[i])
        self.assertEqual(len(car2.renditions()), 5)

    def test_bad_input(self):
        with self.assertRaises(CarError):
            Car(b"NOTABOMS" + self.data[8:])
        for cut in (0, 10, 31, 40, len(self.data) - 5):
            with self.assertRaises(CarError):
                Car(self.data[:cut])
        with self.assertRaises(CarError):
            self.car.block(9999)

    @unittest.skipUnless(os.environ.get("DAVIDTUBE_REAL_CAR"), "set DAVIDTUBE_REAL_CAR")
    def test_real_catalog(self):
        with open(os.environ["DAVIDTUBE_REAL_CAR"], "rb") as fh:
            data = fh.read()
        car = Car(data)
        f = car.facets()
        self.assertEqual(len(f), 612)
        self.assertEqual(len(car.renditions()), 1866)
        for t in TARGETS:
            self.assertIn(t, f)
        self.assertEqual(car.to_bytes(), data)


if __name__ == "__main__":
    unittest.main()

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

    def _rend_nodes(self):
        tree = self.car.block(self.car._var("RENDITIONS"))
        root = struct.unpack(">I", tree[8:12])[0]
        first = struct.unpack(">I", self.car.block(root)[12:16])[0]
        second = struct.unpack(">I", self.car.block(first)[4:8])[0]  # forward link
        return root, first, second

    def _patched(self, idx, data):
        self.car.replace_block(idx, data)
        return Car(self.car.to_bytes())

    def test_internal_self_cycle(self):
        root, _, _ = self._rend_nodes()
        car = self._patched(root, struct.pack(">HHII", 0, 1, 0, 0) + struct.pack(">II", root, 0))
        with self.assertRaises(CarError):
            car.renditions()

    def test_internal_two_node_cycle(self):
        root, first, _ = self._rend_nodes()
        self.car.replace_block(first, struct.pack(">HHII", 0, 1, 0, 0) + struct.pack(">II", root, 0))
        car = Car(self.car.to_bytes())
        with self.assertRaises(CarError):
            car.renditions()

    def test_leaf_forward_cycle(self):
        _, first, second = self._rend_nodes()
        blk = bytearray(self.car.block(second))
        struct.pack_into(">I", blk, 4, first)
        car = self._patched(second, bytes(blk))
        with self.assertRaises(CarError):
            car.renditions()

    def test_bad_keyformat_magic(self):
        kf = self.car._var("KEYFORMAT")
        car = self._patched(kf, b"XXXX" + self.car.block(kf)[4:])
        with self.assertRaises(CarError):
            car.renditions()

    def test_replace_block_bounds(self):
        for i in (0, -1, 9999):
            with self.assertRaises(CarError):
                self.car.replace_block(i, b"x")

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

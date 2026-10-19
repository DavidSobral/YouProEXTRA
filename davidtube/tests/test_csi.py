import os
import struct
import unittest

from davidtube.tests.fixtures import (BITMAP_INFO, BYTES_PER_ROW, COMPOSITION, IDENT, METRICS,
                                      SCALE, SLICES, build_catalog, make_csi, make_link_csi)
from davidtube.tools.car import Car, CarError
from davidtube.tools.csi import (CELM_FLAGS, build_image_csi, decode_image_payload, find_template,
                                 info_list, parse_csi_header, row_bytes)


def pixels(w, h):
    return bytes((x * 7 + y * 13 + c) & 0xFF for y in range(h) for x in range(w) for c in range(4))


class CsiTests(unittest.TestCase):
    def setUp(self):
        self.template = make_csi()
        self.w, self.h = 13, 7
        self.bgra = pixels(self.w, self.h)
        self.csi = build_image_csi(self.template, "youtube_logo@2x.png", self.w, self.h, 200,
                                   self.bgra)

    def test_parse_template(self):
        hd = parse_csi_header(self.template)
        self.assertEqual((hd.width, hd.height, hd.scale100), (20, 10, 200))
        self.assertEqual(hd.pixel_format, b"BGRA")
        self.assertEqual(hd.name, "tmpl@2x.png")
        self.assertEqual(hd.info_length, 104)
        self.assertEqual(hd.payload_kind, b"CELM")

    def test_parse_link(self):
        hd = parse_csi_header(make_link_csi())
        self.assertEqual((hd.width, hd.height), (244, 96))
        self.assertEqual(hd.payload_kind, b"INLK")

    def test_parse_rejects_garbage(self):
        for bad in (b"", b"XXXX" + self.template[4:], self.template[:100],
                    self.template[:-1]):
            with self.assertRaises(CarError):
                parse_csi_header(bad)

    def test_header_fields(self):
        hd = parse_csi_header(self.csi)
        self.assertEqual((hd.width, hd.height, hd.scale100), (13, 7, 200))
        self.assertEqual(hd.name, "youtube_logo@2x.png")
        self.assertEqual(hd.pixel_format, b"BGRA")
        self.assertEqual(hd.payload_kind, b"CELM")

    def test_header_otherwise_verbatim(self):
        t, c = self.template, self.csi
        self.assertEqual(c[:12], t[:12])        # tag, version, flags
        self.assertEqual(c[24:40], t[24:40])    # pixel format, color space, mod date, layout
        self.assertEqual(c[172:180], t[172:180])  # bitmap count, reserved

    def test_sizes_self_consistent(self):
        il, = struct.unpack_from("<I", self.csi, 168)
        ps, = struct.unpack_from("<I", self.csi, 180)
        self.assertEqual(184 + il + ps, len(self.csi))
        self.assertEqual(sum(8 + len(d) for _, d in info_list(self.csi)), il)

    def test_info_list_rewritten(self):
        got = info_list(self.csi)
        want = info_list(self.template)
        self.assertEqual([t for t, _ in got], [t for t, _ in want])
        g, w = dict(got), dict(want)
        self.assertEqual(g[SLICES], struct.pack("<5I", 1, 0, 0, 13, 7))
        self.assertEqual(g[METRICS], struct.pack("<7I", 1, 0, 0, 0, 0, 13, 7))
        self.assertEqual(g[BYTES_PER_ROW], struct.pack("<I", 64))
        self.assertEqual(g[COMPOSITION], w[COMPOSITION])
        self.assertEqual(g[BITMAP_INFO], w[BITMAP_INFO])

    def test_row_bytes(self):
        self.assertEqual([row_bytes(w) for w in (8, 13, 122, 244, 366, 387)],
                         [32, 64, 512, 992, 1472, 1568])

    def test_payload_round_trip(self):
        self.assertEqual(decode_image_payload(self.csi), self.bgra)

    def test_payload_framing(self):
        il, = struct.unpack_from("<I", self.csi, 168)
        p = self.csi[184 + il:]
        magic, flags, comp, nchunks = struct.unpack_from("<4sIII", p)
        self.assertEqual((magic, flags, comp), (b"MLEC", CELM_FLAGS, 4))
        stride, off, rows_seen, raw = row_bytes(self.w), 16, [], b""
        for _ in range(nchunks):
            tag, z1, z2, rows, clen = struct.unpack_from("<4sIIII", p, off)
            self.assertEqual((tag, z1, z2), (b"KCBC", 0, 0))
            stream = p[off + 20:off + 20 + clen]
            # LZFSE stream: one uncompressed block ('bvx-') then end of stream ('bvx$')
            self.assertEqual(stream[:4], b"bvx-")
            n, = struct.unpack_from("<I", stream, 4)
            self.assertEqual(n, rows * stride)
            self.assertEqual(stream[8 + n:], b"bvx$")
            raw += stream[8:8 + n]
            rows_seen.append(rows)
            off += 20 + clen
        self.assertEqual(off, len(p))
        self.assertEqual(rows_seen, [2, 2, 2, 1])  # height // 3 rows, remainder last
        for y in range(self.h):
            row = raw[y * stride:(y + 1) * stride]
            self.assertEqual(row[:self.w * 4], self.bgra[y * self.w * 4:(y + 1) * self.w * 4])
            self.assertEqual(row[self.w * 4:], b"\0" * (stride - self.w * 4))

    def test_target_sizes(self):
        for w, h, s in ((122, 48, 100), (244, 96, 200), (387, 144, 300), (1, 1, 100),
                        (2, 2, 100)):
            bgra = pixels(w, h)
            csi = build_image_csi(self.template, "n", w, h, s, bgra)
            hd = parse_csi_header(csi)
            self.assertEqual((hd.width, hd.height, hd.scale100), (w, h, s))
            self.assertEqual(decode_image_payload(csi), bgra)

    def test_name_limits(self):
        build_image_csi(self.template, "a" * 127, 1, 1, 100, b"\0" * 4)
        with self.assertRaises(ValueError):
            build_image_csi(self.template, "a" * 128, 1, 1, 100, b"\0" * 4)

    def test_bad_pixel_length(self):
        with self.assertRaises(ValueError):
            build_image_csi(self.template, "n", 2, 2, 100, b"\0" * 15)
        with self.assertRaises(ValueError):
            build_image_csi(self.template, "n", 0, 2, 100, b"")

    def test_rejects_link_template(self):
        with self.assertRaises(CarError):
            build_image_csi(make_link_csi(), "n", 1, 1, 100, b"\0" * 4)


class FindTemplateTests(unittest.TestCase):
    def catalog(self, blobs):
        facets = [("f%d" % i, {IDENT: i + 1}) for i in range(len(blobs))]
        rends = [({IDENT: i + 1, SCALE: 2}, b) for i, b in enumerate(blobs)]
        return Car(build_catalog(facets, rends))

    def test_picks_smallest_standalone_bgra(self):
        big = make_csi(64, 64, payload=b"MLEC" + struct.pack("<III", 0, 11, 500) + b"x" * 500)
        small = make_csi(8, 8, name=b"small.png")
        blobs = [make_link_csi(),
                 make_csi(8, 8, layout=1004, name=b"ZZZZPackedAsset-2.0.0-gamut0"),
                 make_csi(4, 4, pixel_format=b" 8AG"),
                 make_csi(4, 4, flags=0x18),  # unexpected flag bits
                 big, small]
        self.assertEqual(find_template(self.catalog(blobs)), small)

    def test_none_found(self):
        with self.assertRaises(CarError):
            find_template(self.catalog([make_link_csi(), make_csi(4, 4, pixel_format=b" 8AG")]))

    @unittest.skipUnless(os.environ.get("DAVIDTUBE_REAL_CAR"), "set DAVIDTUBE_REAL_CAR")
    def test_real_catalog(self):
        with open(os.environ["DAVIDTUBE_REAL_CAR"], "rb") as fh:
            car = Car(fh.read())
        tpl = find_template(car)
        th = parse_csi_header(tpl)
        self.assertEqual((th.pixel_format, th.payload_kind), (b"BGRA", b"CELM"))
        bgra = pixels(244, 96)
        csi = build_image_csi(tpl, "youtube_logo@2x.png", 244, 96, 200, bgra)
        hd = parse_csi_header(csi)
        self.assertEqual((hd.width, hd.height, hd.scale100, hd.name),
                         (244, 96, 200, "youtube_logo@2x.png"))
        il, = struct.unpack_from("<I", csi, 168)
        ps, = struct.unpack_from("<I", csi, 180)
        self.assertEqual(184 + il + ps, len(csi))
        d = dict(info_list(csi))
        self.assertEqual(d[SLICES], struct.pack("<5I", 1, 0, 0, 244, 96))
        self.assertEqual(d[METRICS], struct.pack("<7I", 1, 0, 0, 0, 0, 244, 96))
        self.assertEqual(d[BYTES_PER_ROW], struct.pack("<I", 992))
        self.assertEqual(decode_image_payload(csi), bgra)
        # the link rendition being replaced shares the template's header conventions
        ident = car.facets()["youtube_logo"][IDENT]
        old = [r for r in car.renditions() if r.attrs[IDENT] == ident and r.attrs[SCALE] == 2]
        oh = parse_csi_header(car.block(old[0].value_block))
        self.assertEqual((oh.width, oh.height, oh.payload_kind), (244, 96, b"INLK"))
        self.assertEqual(csi[8:12], car.block(old[0].value_block)[8:12])  # flags


if __name__ == "__main__":
    unittest.main()

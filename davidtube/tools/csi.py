"""Build standalone bitmap renditions (CSI blobs) for an Apple asset catalog.

CSI layout (little-endian), as observed in the YouTube 21.41.5 catalogs:

    0   'ISTC'   tag                    4   version (1)
    8   rendition flags                 12  width        16  height
    20  scale x100                      24  pixel format (bytes 'BGRA' / ' 8AG')
    28  color space                     32  modification date (0)
    36  layout u16 (12 = image, 1003 = internal link, 1004 = packed atlas)
    38  reserved u16                    40  name, char[128], NUL terminated
    168 info-list length                172 bitmap count (1)
    176 reserved                        180 payload length
    184 info list: TLVs (tag u32, length u32, data), then the payload.

Info-list entries of a standalone image: 1001 slices (count, x, y, w, h),
1003 metrics (count, 2 insets, w, h), 1004 blend mode + opacity, 1006 bitmap
info, 1007 bytes per row.  Links keep their target in entry 1010 ('INLK')
and have an empty payload.

Payload choice (evidence, see task-2 report): no catalog in the IPA (25
catalogs, ~16k renditions) contains a ZIP (2) or uncompressed (0) CELM
payload, so their framing cannot be verified.  The only non-DeepMap bitmaps
are LZFSE (4) renditions in the main Assets.car, whose framing was verified
by decoding them with Apple's reference lzfse decoder:

    'CELM' (bytes 'MLEC'), flags 1, compression 4, chunk count,
    chunks: 'CBCK' (bytes 'KCBC'), 0, 0, row count, length, LZFSE stream

with height // 3 rows per chunk plus a remainder chunk; each chunk decodes
to rows * bytes-per-row bytes.  Rows are premultiplied BGRA padded with
zeros to bytes-per-row = width * 4 rounded up to a multiple of 32 (true for
all 446 BGRA bitmaps in the IPA), and entry 1007 records that value.

This module emits exactly that framing.  Each LZFSE stream is one
uncompressed block ('bvx-', byte count, raw bytes) plus the end marker
('bvx$'), a valid LZFSE stream that the reference decoder accepts, so no
compressor is needed.  Not verifiable here: that CoreUI's LZFSE path accepts
uncompressed blocks (libcompression's decoder is the reference decoder) and
that the pixels are expected premultiplied (no semi-transparent pixel in the
decodable samples).  Apple's assetutil and the device validate both.
"""
import struct
from dataclasses import dataclass

from davidtube.tools.car import CarError

HEADER = 184
NAME_OFF, NAME_LEN = 40, 128
SLICES, METRICS, BYTES_PER_ROW, LINK = 1001, 1003, 1007, 1010
TEMPLATE_TAGS = [1001, 1003, 1004, 1006, 1007]
LAYOUT_IMAGE = 12
CELM, CBCK = b"MLEC", b"KCBC"  # u32 FourCCs 'CELM' and 'CBCK' as stored
LZFSE = 4
# CELM flags word.  Measured with the system CoreUI on macOS (davidtube/probe):
# bit 1 (2) makes the bitmap opaque (alpha dropped), 0 draws nothing at all, and
# 1 keeps the alpha channel and the pixels.  The LZFSE sample in the IPA (3) is opaque.
CELM_FLAGS = 1
LZ_RAW, LZ_END = b"bvx-", b"bvx$"


@dataclass
class CsiHeader:
    width: int
    height: int
    scale100: int
    pixel_format: bytes
    name: str
    info_length: int
    payload_kind: bytes  # b'CELM' or b'INLK'
    layout: int
    flags: int


def _u32(data, off):
    try:
        return struct.unpack_from("<I", data, off)[0]
    except struct.error as e:
        raise CarError("truncated CSI at offset %d" % off) from e


def _check(csi):
    if len(csi) < HEADER or csi[:4] != b"ISTC":
        raise CarError("not a CSI")
    il, ps = _u32(csi, 168), _u32(csi, 180)
    if HEADER + il + ps != len(csi):
        raise CarError("CSI length mismatch")
    return il, ps


def info_list(csi):
    """[(tag, data)] of the CSI's info list, in order."""
    il, _ = _check(csi)
    out, p, end = [], HEADER, HEADER + il
    while p < end:
        tag, ln = _u32(csi, p), _u32(csi, p + 4)
        if p + 8 + ln > end:
            raise CarError("info list entry overruns")
        out.append((tag, bytes(csi[p + 8:p + 8 + ln])))
        p += 8 + ln
    return out


def parse_csi_header(csi):
    il, ps = _check(csi)
    payload = csi[HEADER + il:]
    if ps >= 16 and payload[:4] == CELM:
        kind = b"CELM"
    elif ps == 0 and any(t == LINK and d[:4] == b"KLNI" for t, d in info_list(csi)):
        kind = b"INLK"
    else:
        raise CarError("unknown CSI payload")
    w, h, s = struct.unpack_from("<III", csi, 12)
    name = bytes(csi[NAME_OFF:NAME_OFF + NAME_LEN]).split(b"\0")[0].decode("utf-8", "replace")
    return CsiHeader(w, h, s, bytes(csi[24:28]), name, il, kind,
                     struct.unpack_from("<H", csi, 36)[0], _u32(csi, 8))


def row_bytes(width):
    return (width * 4 + 31) // 32 * 32


def _lzfse_stored(raw):
    return LZ_RAW + struct.pack("<I", len(raw)) + raw + LZ_END


def _payload(width, height, bgra):
    stride, tight = row_bytes(width), width * 4
    pad = b"\0" * (stride - tight)
    per = max(1, height // 3)
    chunks = []
    for y0 in range(0, height, per):
        rows = min(per, height - y0)
        raw = b"".join(bgra[y * tight:(y + 1) * tight] + pad for y in range(y0, y0 + rows))
        stream = _lzfse_stored(raw)
        chunks.append(CBCK + struct.pack("<IIII", 0, 0, rows, len(stream)) + stream)
    return CELM + struct.pack("<III", CELM_FLAGS, LZFSE, len(chunks)) + b"".join(chunks)


def build_image_csi(template, name, width, height, scale100, bgra):
    """A standalone image CSI showing `bgra` (premultiplied, tightly packed
    width*4 rows).  Header and info list come from `template`; size, scale,
    name, slices, metrics and bytes-per-row are rewritten."""
    nm = name.encode("utf-8")
    if len(nm) > NAME_LEN - 1:
        raise ValueError("name longer than %d bytes" % (NAME_LEN - 1))
    if width <= 0 or height <= 0 or scale100 <= 0:
        raise ValueError("bad size or scale")
    if len(bgra) != width * height * 4:
        raise ValueError("expected %d pixel bytes, got %d" % (width * height * 4, len(bgra)))
    hd = parse_csi_header(template)
    if hd.payload_kind != b"CELM" or hd.layout != LAYOUT_IMAGE:
        raise CarError("template is not a standalone image")
    new = {SLICES: struct.pack("<5I", 1, 0, 0, width, height),
           METRICS: struct.pack("<7I", 1, 0, 0, 0, 0, width, height),
           BYTES_PER_ROW: struct.pack("<I", row_bytes(width))}
    entries = info_list(template)
    if [t for t, _ in entries] != TEMPLATE_TAGS:
        raise CarError("template info list is not the standard image list")
    infos = b"".join(struct.pack("<II", t, len(new.get(t, d))) + new.get(t, d)
                     for t, d in entries)
    payload = _payload(width, height, bytes(bgra))
    head = bytearray(template[:HEADER])
    struct.pack_into("<III", head, 12, width, height, scale100)
    head[NAME_OFF:NAME_OFF + NAME_LEN] = nm.ljust(NAME_LEN, b"\0")
    struct.pack_into("<I", head, 168, len(infos))
    struct.pack_into("<I", head, 180, len(payload))
    return bytes(head) + infos + payload


def decode_image_payload(csi):
    """Tightly packed BGRA of a CSI written by build_image_csi (stored LZFSE
    blocks only); raises CarError for anything else."""
    hd = parse_csi_header(csi)
    p = HEADER + hd.info_length
    if hd.payload_kind != b"CELM" or struct.unpack_from("<II", csi, p + 4) != (CELM_FLAGS, LZFSE):
        raise CarError("not a chunked LZFSE payload")
    stride, tight = row_bytes(hd.width), hd.width * 4
    nchunks, off, out, total = _u32(csi, p + 12), p + 16, [], 0
    for _ in range(nchunks):
        if csi[off:off + 4] != CBCK:
            raise CarError("bad chunk")
        rows, clen = _u32(csi, off + 12), _u32(csi, off + 16)
        s = csi[off + 20:off + 20 + clen]
        raw = b""
        while s[:4] == LZ_RAW:
            n = _u32(s, 4)
            raw += s[8:8 + n]
            s = s[8 + n:]
        if s != LZ_END or len(raw) != rows * stride:
            raise CarError("bad LZFSE chunk")
        out.extend(raw[y * stride:y * stride + tight] for y in range(rows))
        total += rows
        off += 20 + clen
    if off != len(csi) or total != hd.height:
        raise CarError("payload size mismatch")
    return b"".join(out)


def find_template(car):
    """Smallest standalone BGRA image rendition with the standard info list."""
    best = None
    for r in car.renditions():
        blob = car.block(r.value_block)
        try:
            hd = parse_csi_header(blob)
            tags = [t for t, _ in info_list(blob)]
        except CarError:
            continue
        if (hd.payload_kind == b"CELM" and hd.pixel_format == b"BGRA"
                and hd.layout == LAYOUT_IMAGE and hd.flags & ~0x10 == 0
                and tags == TEMPLATE_TAGS
                and not hd.name.startswith("ZZZZPackedAsset")
                and (best is None or len(blob) < len(best))):
            best = blob
    if best is None:
        raise CarError("no standalone BGRA image rendition to use as template")
    return best

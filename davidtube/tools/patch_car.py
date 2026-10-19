#!/usr/bin/env python3
"""Put the DavidTube logo into YouTube's Innertube_Resources.bundle/Assets.car.

Usage: python3 -I davidtube/tools/patch_car.py IN.ipa OUT.ipa

Every rendition (scales 1x, 2x, 3x) of the eight wordmark facets in TARGETS is
replaced by a standalone BGRA image CSI of the same size, scale and name
showing the DavidTube logo.  All other catalog blocks stay byte-identical.
The result is re-parsed and verified before it is written.

All or nothing: on any problem OUT.ipa becomes a byte-identical copy of
IN.ipa, a `::warning::DavidTube logo: <reason>` line is printed and the exit
code is still 0, so the build goes on with the original logo.  Wrong usage
exits with 2.
"""
import os
import re
import shutil
import struct
import sys
import tempfile
import zipfile

if __name__ == "__main__":  # run as a script under -I: make `davidtube` importable
    _ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _ROOT not in sys.path:
        sys.path.append(_ROOT)

from davidtube.tools.car import Car, CarError  # noqa: E402
from davidtube.tools.csi import (LAYOUT_IMAGE, build_image_csi, decode_image_payload,  # noqa: E402
                                 find_template, parse_csi_header)

try:
    from davidtube.tools.render import render_logo
except ImportError as _err:  # e.g. Pillow missing on the runner: fail safe at patch time
    def render_logo(variant, width, height, _msg="logo renderer unavailable: %s" % _err):
        raise CarError(_msg)

TARGETS = ("youtube_logo", "youtube_logo_dark", "youtube_logo_cairo",
           "youtube_logo_dark_cairo", "youtube_premium_logo", "youtube_premium_logo_white",
           "youtube_premium_logo_cairo", "youtube_premium_logo_dark_cairo")
SCALES = (1, 2, 3)
IDENT, SCALE = 17, 12  # rendition key attributes: identifier, scale
CAR_PATH = "Payload/YouTube.app/Innertube_Resources.bundle/Assets.car"
_CAR_RE = re.compile(r"Payload/[^/]+\.app/Innertube_Resources\.bundle/Assets\.car\Z")
_INDEX_OFF = 16  # BOM header field: offset of the block index table


def variant_for(name):
    """'dark' (white-text logo) for dark/white facets, else 'light'."""
    return "dark" if "dark" in name or name.endswith("_white") else "light"


class _Subset:
    """The view of a Car that find_template needs, without some renditions."""

    def __init__(self, car, renditions):
        self._car, self._rends = car, renditions

    def renditions(self):
        return self._rends

    def block(self, i):
        return self._car.block(i)


def _plan(car, facets, rends):
    """[(facet, value_block, header)] for every target rendition, checked strictly."""
    ids = {}
    for name in TARGETS:
        if name not in facets or IDENT not in facets[name]:
            raise CarError("facet %s not found in the catalog" % name)
        ids[facets[name][IDENT]] = name
    if len(ids) != len(TARGETS):
        raise CarError("target facets share an identifier")
    uses = {}
    for r in rends:
        uses[r.value_block] = uses.get(r.value_block, 0) + 1
        uses[r.key_block] = uses.get(r.key_block, 0) + 1
    by_facet = {name: [] for name in TARGETS}
    for r in rends:
        if r.attrs.get(IDENT) in ids:
            by_facet[ids[r.attrs[IDENT]]].append(r)
    plan = []
    for name in TARGETS:
        rs = by_facet[name]
        scales = sorted(r.attrs.get(SCALE) for r in rs)
        if scales != list(SCALES):
            raise CarError("facet %s: expected one rendition per scale %s, found scales %s"
                           % (name, list(SCALES), scales))
        for r in rs:
            where = "facet %s @%dx" % (name, r.attrs[SCALE])
            if r.value_block == 0 or uses[r.value_block] != 1:
                raise CarError("%s: value block %d is shared" % (where, r.value_block))
            hd = parse_csi_header(car.block(r.value_block))
            if hd.scale100 != 100 * r.attrs[SCALE]:
                raise CarError("%s: CSI scale %d disagrees with key" % (where, hd.scale100))
            if hd.pixel_format != b"BGRA":
                raise CarError("%s: pixel format %r is not BGRA" % (where, hd.pixel_format))
            if hd.width <= 0 or hd.height <= 0 or not hd.name:
                raise CarError("%s: bad size or empty name" % where)
            plan.append((name, r.value_block, hd))
    return plan


def patch_catalog(data):
    """Return the patched catalog bytes; raises CarError if anything is off."""
    car = Car(data)
    facets, rends = car.facets(), car.renditions()
    plan = _plan(car, facets, rends)
    targets = {b for _, b, _ in plan}
    # Template from non-target renditions only, so a second run picks the same one.
    template = find_template(_Subset(car, [r for r in rends if r.value_block not in targets]))
    expected = {}
    for facet, block, hd in plan:
        bgra = render_logo(variant_for(facet), hd.width, hd.height)
        try:
            csi = build_image_csi(template, hd.name, hd.width, hd.height, hd.scale100, bgra)
        except ValueError as e:
            raise CarError("facet %s: %s" % (facet, e)) from e
        car.replace_block(block, csi)
        expected[block] = (hd.name, hd.width, hd.height, hd.scale100, bgra)
    out = car.to_bytes()
    _verify_catalog(data, out, expected)
    return out


def _verify_catalog(data, out, expected):
    """Re-parse `out` and check it against `data` and the intended renditions."""
    old, new = Car(data), Car(out)
    n = old.block_count()
    if new.block_count() != n:
        raise CarError("verify: block count changed")
    # Original bytes untouched except the index entries of the replaced blocks,
    # and the new blocks live (without overlapping) in the appended tail.
    index_off, = struct.unpack_from(">I", data, _INDEX_OFF)
    prefix = bytearray(data)
    spans = []
    for i in expected:
        e = index_off + 4 + 8 * i
        prefix[e:e + 8] = out[e:e + 8]
        spans.append(struct.unpack_from(">II", out, e))
    if len(out) < len(data) or out[:len(data)] != prefix:
        raise CarError("verify: original region of the file changed")
    end = len(data)
    for addr, length in sorted(spans):
        if addr < end or addr + length > len(out):
            raise CarError("verify: replaced blocks overlap")
        end = addr + length
    for i in range(n):
        if i not in expected and new.block(i) != old.block(i):
            raise CarError("verify: untouched block %d changed" % i)
    if new.facets() != old.facets():
        raise CarError("verify: facets changed")
    if new.renditions() != old.renditions():
        raise CarError("verify: rendition keys changed")
    for i, (name, w, h, s, bgra) in expected.items():
        blob = new.block(i)
        hd = parse_csi_header(blob)
        if (hd.payload_kind, hd.layout, hd.pixel_format) != (b"CELM", LAYOUT_IMAGE, b"BGRA"):
            raise CarError("verify: %s is not a standalone BGRA image" % name)
        if (hd.name, hd.width, hd.height, hd.scale100) != (name, w, h, s):
            raise CarError("verify: %s has wrong name/size/scale" % name)
        if decode_image_payload(blob) != bgra:
            raise CarError("verify: %s decoded pixels differ" % name)


def _find_car(infos):
    exact = [i for i in infos if i.filename == CAR_PATH]
    found = exact or [i for i in infos if _CAR_RE.match(i.filename)]
    if not found:
        raise CarError("Innertube_Resources.bundle/Assets.car not found in the IPA")
    if len(found) > 1:
        raise CarError("more than one Innertube_Resources.bundle/Assets.car in the IPA")
    return found[0]


def _strip_zip64(extra):
    """Drop zip64 (0x0001) extra records; zipfile writes its own when needed."""
    out, p = b"", 0
    while p + 4 <= len(extra):
        tag, ln = struct.unpack_from("<HH", extra, p)
        if p + 4 + ln > len(extra):
            raise ValueError("malformed zip extra field")
        if tag != 1:
            out += extra[p:p + 4 + ln]
        p += 4 + ln
    if p != len(extra):
        raise ValueError("malformed zip extra field")
    return out


def _clone(info):
    zi = zipfile.ZipInfo(info.filename, info.date_time)
    for attr in ("compress_type", "comment", "create_system", "create_version",
                 "extract_version", "internal_attr", "external_attr", "file_size"):
        setattr(zi, attr, getattr(info, attr))
    zi.extra = _strip_zip64(info.extra)
    return zi


def _write_ipa(zin, infos, car_info, patched, path):
    with zipfile.ZipFile(path, "w", allowZip64=True) as zout:
        zout.comment = zin.comment
        for info in infos:
            zi = _clone(info)
            if info is car_info:
                zi.file_size = len(patched)
                zout.writestr(zi, patched)
            else:
                with zin.open(info) as src, zout.open(zi, "w") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)


def _verify_ipa(path, infos, car_info, patched):
    with zipfile.ZipFile(path) as z:
        out = z.infolist()
        if [i.filename for i in out] != [i.filename for i in infos]:
            raise CarError("verify: IPA member list changed")
        for a, b in zip(infos, out):
            if ((b.compress_type, b.date_time, b.external_attr)
                    != (a.compress_type, a.date_time, a.external_attr)):
                raise CarError("verify: IPA member %s attributes changed" % a.filename)
            if a is car_info:
                if z.read(b) != patched:
                    raise CarError("verify: Assets.car in the IPA differs")
            elif (b.CRC, b.file_size) != (a.CRC, a.file_size):
                raise CarError("verify: IPA member %s changed" % a.filename)


def _patch_ipa(ipa_in, ipa_out):
    out_dir = os.path.dirname(os.path.abspath(ipa_out))
    with zipfile.ZipFile(ipa_in) as zin:
        infos = zin.infolist()
        car_info = _find_car(infos)
        patched = patch_catalog(zin.read(car_info))
        fd, tmp = tempfile.mkstemp(prefix=".davidtube-", suffix=".ipa", dir=out_dir)
        os.close(fd)
        try:
            _write_ipa(zin, infos, car_info, patched, tmp)
            _verify_ipa(tmp, infos, car_info, patched)
        except BaseException:
            os.unlink(tmp)
            raise
    try:
        os.replace(tmp, ipa_out)
    except BaseException:
        os.unlink(tmp)
        raise


def _reason(e):
    text = str(e) if isinstance(e, CarError) else "%s: %s" % (type(e).__name__, e)
    return " ".join(text.split()) or type(e).__name__


def patch_ipa(ipa_in, ipa_out):
    """Write ipa_out patched and return True, or write it as an exact copy of
    ipa_in, print a ::warning:: line and return False.  Never raises."""
    try:
        _patch_ipa(ipa_in, ipa_out)
        return True
    except Exception as e:
        reason = _reason(e)
    try:
        if not (os.path.exists(ipa_out) and os.path.samefile(ipa_in, ipa_out)):
            shutil.copyfile(ipa_in, ipa_out)
        reason += "; IPA left unchanged"
    except Exception as e:
        reason += "; copying the input also failed: %s" % _reason(e)
    try:
        print("::warning::DavidTube logo: %s" % reason, flush=True)
    except Exception:
        pass
    return False


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: patch_car.py IN.ipa OUT.ipa", file=sys.stderr)
        return 2
    if patch_ipa(args[0], args[1]):
        print("DavidTube logo: Assets.car patched (%d facets x %d scales)"
              % (len(TARGETS), len(SCALES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

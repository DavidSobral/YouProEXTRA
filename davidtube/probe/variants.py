"""Write patched Assets.car variants that differ only in two header flag words.

Usage: variants.py IPA OUTDIR     (writes OUTDIR/v_<celm>_<hdr>.car)
celm = CELM flags word of the bitmap payload, hdr = rendition flags in the CSI header.
"""
import os
import struct
import sys
import zipfile

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from davidtube.tools import csi, patch_car  # noqa: E402


def main(ipa, out):
    with zipfile.ZipFile(ipa) as z:
        data = z.read(patch_car.find_car(z.infolist()).filename)
    os.makedirs(out, exist_ok=True)
    orig = csi.build_image_csi
    for celm in (0, 1, 2, 3):
        for hdr in (0x10, 0x0):
            csi.CELM_FLAGS = celm

            def build(*a, _h=hdr, **k):
                b = bytearray(orig(*a, **k))
                struct.pack_into("<I", b, 8, _h)
                return bytes(b)
            patch_car.build_image_csi = build
            try:
                blob = patch_car.patch_catalog(data)
            except Exception as e:  # report and go on
                print("variant celm=%d hdr=0x%x failed: %s" % (celm, hdr, e))
                continue
            with open(os.path.join(out, "v_%d_%x.car" % (celm, hdr)), "wb") as f:
                f.write(blob)


if __name__ == "__main__":
    main(*sys.argv[1:3])

"""Shared helpers: a fake `assetutil` placed on PATH."""
import os
import stat
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

_LISTER = r'''
import json, sys
sys.path.insert(0, %(root)r)
from davidtube.tools.car import Car
from davidtube.tools.csi import parse_csi_header
car = Car(open(sys.argv[2], "rb").read())
names = {a[17]: n for n, a in car.facets().items()}
out = [{"AssetType": "Header", "Version": 1}]
for r in car.renditions():
    hd = parse_csi_header(car.block(r.value_block))
    out.append({"Name": names.get(r.attrs.get(17), "?"), "Scale": r.attrs.get(12),
                "PixelWidth": hd.width, "PixelHeight": hd.height,
                "SizeOnDisk": len(car.block(r.value_block)), "Encoding": hd.pixel_format.decode("latin1")})
%(extra)s
json.dump(out, sys.stdout)
'''


def make_fake_assetutil(directory, script_body=None, lister_extra=""):
    """Create <directory>/assetutil.  Default: list the catalog given as the
    argument after --info.  `script_body` (sh) replaces the whole script."""
    path = os.path.join(directory, "assetutil")
    if script_body is None:
        helper = os.path.join(directory, "lister.py")
        with open(helper, "w") as f:
            f.write(_LISTER % {"root": ROOT, "extra": lister_extra})
        script_body = '#!/bin/sh\nexec %s -I %s "$@"\n' % (sys.executable, helper)
    with open(path, "w") as f:
        f.write(script_body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def full_listing(extra=()):
    """A plausible assetutil listing: header, all 8 real targets x 3 scales, other entries."""
    from davidtube.tools.patch_car import SCALES, TARGETS
    out = [{"AssetType": "Header", "Version": 7}]
    for n in TARGETS:
        for sc in SCALES:
            out.append({"Name": n, "Scale": sc, "PixelWidth": 100 * sc, "PixelHeight": 20 * sc,
                        "SizeOnDisk": 50})
    out.append({"Name": "ic_x", "Scale": 3, "PixelWidth": 6, "PixelHeight": 6, "SizeOnDisk": 10})
    return out + list(extra)

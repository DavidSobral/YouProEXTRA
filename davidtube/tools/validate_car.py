#!/usr/bin/env python3
"""Check that a patched Assets.car differs from the original only in the logo.

Usage: python3 -I davidtube/tools/validate_car.py ORIGINAL.car PATCHED.car
       python3 -I davidtube/tools/validate_car.py --extract IN.ipa OUT.car

Runs `assetutil --info` (macOS only) on both catalogs and compares the listings
with compare_listings().  Exit codes: 0 = OK (prints `OK`), 1 = unexpected
differences or assetutil failed / printed non-JSON, 2 = wrong usage,
3 = assetutil is not on PATH (nothing was validated).

`--extract` writes the Innertube_Resources.bundle/Assets.car of an IPA to a file.

Assumptions about `assetutil --info` (to be confirmed on a Mac): the output is
a JSON array of dicts; the first may be a header without `Name`; every other
entry is one rendition with `Name` (facet name, possibly with a `.png` suffix),
`Scale`, `PixelWidth` and `PixelHeight`.  Entries are matched by (Name, Scale);
several entries may share that pair, so they are compared as multisets.
"""
import json
import os
import shutil
import subprocess
import sys

if __name__ == "__main__":  # run as a script under -I: make `davidtube` importable
    _ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _ROOT not in sys.path:
        sys.path.append(_ROOT)

from davidtube.tools.patch_car import SCALES, TARGETS  # noqa: E402

KEEP_KEYS = ("Name", "Scale", "PixelWidth", "PixelHeight")
EXIT_NO_ASSETUTIL = 3


def _base(name):
    return name[:-4] if name.endswith(".png") else name


def _canon(entry):
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


def _label(key):
    name, scale = key
    return "%s (scale %s)" % (name, scale) if scale is not None else str(name)


def _group(listing, targets):
    """({key: [entries]} for non-target, {key: [entries]} for target, [no-name entries])."""
    plain, target, nameless = {}, {}, []
    for e in listing:
        if not isinstance(e, dict) or not isinstance(e.get("Name"), str):
            nameless.append(e)
            continue
        key = (_base(e["Name"]), e.get("Scale"))
        (target if key[0] in targets else plain).setdefault(key, []).append(e)
    return plain, target, nameless


def _diff_multiset(a, b, label, out):
    ca, cb = sorted(_canon(x) for x in a), sorted(_canon(x) for x in b)
    if ca == cb:
        return
    rest = list(cb)
    removed = []
    for x in ca:
        if x in rest:
            rest.remove(x)
        else:
            removed.append(x)
    if removed and rest:
        out.append("changed entry: %s: %s -> %s" % (label, removed[0], rest[0]))
        removed, rest = removed[1:], rest[1:]
    for x in removed:
        out.append("removed entry: %s: %s" % (label, x))
    for x in rest:
        out.append("added entry: %s: %s" % (label, x))


def _shape(e):
    return tuple(e.get(k) for k in KEEP_KEYS)


def _check_targets(listing, targets, which, out):
    """Every target must be listed (>= 1 entry); for the real TARGETS set, with 3 scales."""
    scales = {}
    for e in listing:
        if isinstance(e, dict) and isinstance(e.get("Name"), str) and _base(e["Name"]) in targets:
            scales.setdefault(_base(e["Name"]), set()).add(e.get("Scale"))
    for name in sorted(targets):
        got = scales.get(name)
        if not got:
            out.append("assetutil listing shows no entry for %s (%s catalog)" % (name, which))
        elif set(targets) == set(TARGETS) and len(got) < len(SCALES):
            out.append("assetutil listing shows only %d scale(s) for %s (%s catalog)"
                       % (len(got), name, which))


def compare_listings(orig, patched, targets):
    """Unexpected differences between two assetutil listings (empty list = OK).

    Both listings must contain every target (an empty or unrecognised listing
    is a difference, so nothing is ever "validated" without being checked).
    Target entries (Name, minus a `.png` suffix, in `targets`) may change in any
    way except that each original one must remain, with the same Name, Scale,
    PixelWidth and PixelHeight (only keys present in the original entry are
    compared).  Everything else must be identical and equally numerous."""
    out = []
    _check_targets(orig, targets, "original", out)
    _check_targets(patched, targets, "patched", out)
    po, to, no = _group(orig, targets)
    pp, tp, np_ = _group(patched, targets)
    _diff_multiset(no, np_, "header/unnamed entries", out)
    for key in sorted(set(po) | set(pp), key=lambda k: (str(k[0]), str(k[1]))):
        _diff_multiset(po.get(key, []), pp.get(key, []), _label(key), out)
    for key in sorted(set(to) | set(tp), key=lambda k: (str(k[0]), str(k[1]))):
        eo, ep = to.get(key, []), tp.get(key, [])
        if len(eo) != len(ep):
            out.append("target entry count changed: %s: %d -> %d" % (_label(key), len(eo), len(ep)))
            continue
        rest = list(ep)
        for e in eo:
            want = {k: e[k] for k in KEEP_KEYS if k in e}
            want["Name"] = _base(want["Name"])  # Name is always present here
            for i, p in enumerate(rest):
                if all((_base(p[k]) if k == "Name" else p.get(k)) == v for k, v in want.items()):
                    del rest[i]
                    break
            else:
                out.append("target entry missing or resized: %s: expected %s" % (_label(key), want))
    return out


def _listing(car):
    try:
        proc = subprocess.run(["assetutil", "--info", car], capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError("assetutil failed on %s: %s" % (car, e))
    if proc.returncode != 0:
        raise ValueError("assetutil exited %d on %s" % (proc.returncode, car))
    try:
        text = proc.stdout.decode("utf-8")
        start = text.index("[")  # tolerate leading non-JSON warning lines
        data, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        raise ValueError("assetutil printed non-JSON for %s" % car)
    if not isinstance(data, list):
        raise ValueError("assetutil JSON for %s is not an array" % car)
    return data


def _extract(ipa, dest):
    import zipfile
    from davidtube.tools.patch_car import find_car
    with zipfile.ZipFile(ipa) as z:
        info = find_car(z.infolist())
        with z.open(info) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 3 and args[0] == "--extract":
        try:
            _extract(args[1], args[2])
        except Exception as e:
            print("cannot extract Assets.car: %s" % e, file=sys.stderr)
            return 1
        return 0
    if len(args) != 2:
        print("usage: validate_car.py ORIGINAL.car PATCHED.car", file=sys.stderr)
        return 2
    if shutil.which("assetutil") is None:
        print("assetutil unavailable")
        return EXIT_NO_ASSETUTIL
    try:
        orig, patched = _listing(args[0]), _listing(args[1])
    except ValueError as e:
        print(e)
        return 1
    diffs = compare_listings(orig, patched, set(TARGETS))
    for d in diffs:
        print(d)
    if diffs:
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

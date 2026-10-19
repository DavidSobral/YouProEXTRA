#!/bin/sh
# Usage: sh davidtube/mac_check.sh IPA [OUTDIR]
#
# Mac helper: runs the real patch_ipa.sh on a COPY of IPA and collects
# evidence (assetutil --info of the original and the patched Assets.car) in
# OUTDIR (default ./davidtube-check).  The original IPA is never modified.
# Needs macOS with `assetutil`, python3, and network for `pip install pillow`
# unless DAVIDTUBE_PYTHON points to a python that already has Pillow.
# Always exits 0.

HERE=$(cd "$(dirname "$0")" && pwd) || exit 0
VALIDATOR="$HERE/tools/validate_car.py"

main() {
    ipa=$1
    out=${2:-./davidtube-check}
    if [ -z "$ipa" ] || [ ! -f "$ipa" ]; then
        echo "usage: sh davidtube/mac_check.sh IPA [OUTDIR]  (IPA file not found)"
        return 0
    fi
    if ! command -v assetutil >/dev/null 2>&1; then
        echo "assetutil not found: install Xcode / command line tools (xcode-select --install) and run again."
        return 0
    fi
    mkdir -p "$out" || { echo "cannot create $out"; return 0; }
    out=$(cd "$out" && pwd) || return 0
    case $ipa in /*) ;; *) ipa="$(pwd)/$ipa" ;; esac

    cp "$ipa" "$out/work.ipa" || { echo "cannot copy the IPA"; return 0; }
    echo "== patch_ipa.sh on $out/work.ipa"
    sh "$HERE/patch_ipa.sh" "$out/work.ipa"

    vpy=${DAVIDTUBE_PYTHON:-python3}
    echo "== extracting and listing catalogs"
    "$vpy" -I "$VALIDATOR" --extract "$ipa" "$out/original.car" &&
        "$vpy" -I "$VALIDATOR" --extract "$out/work.ipa" "$out/patched.car" ||
        { echo "cannot extract Assets.car"; return 0; }
    assetutil --info "$out/original.car" >"$out/original.json" 2>"$out/original.err"
    assetutil --info "$out/patched.car" >"$out/patched.json" 2>"$out/patched.err"

    if cmp -s "$ipa" "$out/work.ipa"; then
        echo "== RESULT: work.ipa is IDENTICAL to the original (logo NOT applied, see ::notice::/::warning:: above)"
    else
        echo "== RESULT: work.ipa DIFFERS from the original (logo patched)"
    fi
    "$vpy" -I - "$out/original.json" "$out/patched.json" <<'PY'
import json
import sys

TARGETS = ("youtube_logo", "youtube_logo_dark", "youtube_logo_cairo",
           "youtube_logo_dark_cairo", "youtube_premium_logo", "youtube_premium_logo_white",
           "youtube_premium_logo_cairo", "youtube_premium_logo_dark_cairo")
FIELDS = ("Name", "Scale", "PixelWidth", "PixelHeight", "Encoding", "Compression", "SizeOnDisk")


def load(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        i = text.find("[")
        data = json.loads(text[i:]) if i >= 0 else []
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except Exception as e:
        print("  cannot read %s: %s" % (path, e))
        return []


def pick(entries, name):
    return [e for e in entries
            if str(e.get("Name", "")) in (name, name + ".png")]


def fmt(e):
    return " ".join("%s=%s" % (k, e[k]) for k in FIELDS[1:] if k in e)


orig, patched = load(sys.argv[1]), load(sys.argv[2])
print("entries: original=%d patched=%d" % (len(orig), len(patched)))
for name in TARGETS:
    print("-- %s" % name)
    for label, entries in (("before", orig), ("after ", patched)):
        found = pick(entries, name)
        if not found:
            print("  %s: (no entries)" % label)
        for e in sorted(found, key=lambda e: str(e.get("Scale"))):
            print("  %s: %s" % (label, fmt(e)))
PY
    echo "== evidence folder: $out"
    echo "If anything looks off, zip and send back original.json, patched.json and this terminal output (no secrets in them)."
    return 0
}

main "$@"
exit 0

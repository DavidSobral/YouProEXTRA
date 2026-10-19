#!/bin/sh
# Usage: sh davidtube/probe/run.sh IPA [OUTDIR]
# Mac only (needs Xcode command line tools, python3 + network for Pillow).
# Builds Assets.car variants and prints how the system CoreUI draws youtube_logo
# from each one (and from the original).  Send the whole output back.
HERE=$(cd "$(dirname "$0")" && pwd) || exit 0
ipa=$1
out=${2:-./davidtube-probe}
[ -f "$ipa" ] || { echo "usage: sh davidtube/probe/run.sh IPA [OUTDIR]"; exit 0; }
mkdir -p "$out" || exit 0
out=$(cd "$out" && pwd)
case $ipa in /*) ;; *) ipa="$(pwd)/$ipa" ;; esac
python3 -m venv "$out/venv" >/dev/null 2>&1 && "$out/venv/bin/pip" install -q "pillow>=10,<13" >/dev/null 2>&1
py="$out/venv/bin/python"; [ -x "$py" ] || py=python3
clang -fobjc-arc -framework Foundation -framework CoreGraphics -o "$out/probe" "$HERE/probe.m" 2>"$out/clang.err" ||
    { echo "cannot compile probe.m:"; cat "$out/clang.err"; exit 0; }
"$py" "$HERE/variants.py" "$ipa" "$out" || { echo "cannot build variants"; exit 0; }
"$py" -I -c "
import sys, zipfile
sys.path.insert(0, '$HERE/../..')
from davidtube.tools import patch_car
z = zipfile.ZipFile('$ipa'); open('$out/original.car','wb').write(z.read(patch_car.find_car(z.infolist()).filename))"
for c in original v_0_10 v_0_0 v_1_10 v_1_0 v_2_10 v_2_0 v_3_10 v_3_0; do
    [ -f "$out/$c.car" ] || continue
    echo "== $c (celm_hdr)"
    "$out/probe" "$out/$c.car" youtube_logo
done

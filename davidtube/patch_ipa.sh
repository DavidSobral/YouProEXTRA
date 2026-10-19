#!/bin/sh
# Usage: sh davidtube/patch_ipa.sh IPA
#
# Puts the DavidTube logo into IPA (Assets.car), in place.  IPA is replaced
# only if the patch succeeded AND the patched catalog passed validation with
# macOS `assetutil` (validate_car.py).  In every other case IPA is left
# untouched and the script still exits 0, so the build goes on with the
# original logo.
#
# Environment:
#   RUNNER_TEMP       parent of the temp work dir (default /tmp)
#   DAVIDTUBE_PYTHON  python with Pillow to use instead of building a venv and
#                     running `pip install pillow` (used by the tests; the
#                     workflow does not set it)

HERE=$(cd "$(dirname "$0")" && pwd) || exit 0
PATCHER="$HERE/tools/patch_car.py"
VALIDATOR="$HERE/tools/validate_car.py"
WORK=

cleanup() {
    [ -n "$WORK" ] && rm -rf "$WORK"
}

notice() { echo "::notice::DavidTube logo: $*"; }
warn() { echo "::warning::DavidTube logo: $*"; }

main() {
    ipa=$1
    if [ -z "$ipa" ] || [ ! -f "$ipa" ]; then
        warn "usage: patch_ipa.sh IPA (file not found), nothing done"
        return 0
    fi
    case $ipa in /*) ;; *) ipa="$(pwd)/$ipa" ;; esac

    WORK=$(mktemp -d "${RUNNER_TEMP:-/tmp}/davidtube.XXXXXX") || {
        warn "cannot create a temp dir, logo not applied"
        return 0
    }

    # 1. python with Pillow
    if [ -n "$DAVIDTUBE_PYTHON" ]; then
        py=$DAVIDTUBE_PYTHON
    else
        py="$WORK/venv/bin/python"
        if ! python3 -m venv "$WORK/venv" || ! "$py" -m pip install --quiet "pillow>=10,<13"; then
            warn "cannot install Pillow, IPA left unchanged"
            return 0
        fi
    fi

    # 2. patch
    if ! "$py" -I "$PATCHER" "$ipa" "$WORK/out.ipa"; then
        warn "patching failed, IPA left unchanged"
        return 0
    fi

    vpy=${DAVIDTUBE_PYTHON:-python3}

    # 3. extract both catalogs
    if ! "$vpy" -I "$VALIDATOR" --extract "$ipa" "$WORK/orig.car" ||
        ! "$vpy" -I "$VALIDATOR" --extract "$WORK/out.ipa" "$WORK/patched.car"; then
        warn "cannot extract Assets.car, IPA left unchanged"
        return 0
    fi
    if cmp -s "$WORK/orig.car" "$WORK/patched.car"; then
        notice "logo not applied"
        return 0
    fi

    # 4. validate with assetutil
    "$vpy" -I "$VALIDATOR" "$WORK/orig.car" "$WORK/patched.car" >"$WORK/validate.log" 2>&1
    rc=$?
    case $rc in
    0) ;;
    3)
        notice "assetutil unavailable, logo not applied"
        return 0
        ;;
    *)
        warn "validation failed, IPA left unchanged: $(tr '\n' ' ' <"$WORK/validate.log")"
        return 0
        ;;
    esac

    # 5. atomic replace, keeping the mode of IPA
    tmp="$ipa.davidtube.$$"
    if cp -p "$ipa" "$tmp" && cat "$WORK/out.ipa" >"$tmp" && mv -f "$tmp" "$ipa"; then
        echo "::notice::DavidTube logo patched into IPA"
    else
        rm -f "$tmp"
        warn "cannot replace the IPA, IPA left unchanged"
    fi
    return 0
}

trap cleanup EXIT
main "$@"
exit 0

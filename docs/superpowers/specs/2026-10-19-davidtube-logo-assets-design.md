# DavidTube logo via asset-catalog patch — design

Supersedes `2026-10-18-davidtube-logo-design.md` (hook-based tweak; kept on branch `davidtube-logo`).

## Why the first design was dropped
The tweak `DavidTube.dylib` added one `LC_LOAD_DYLIB` to the YouTube binary. The
~25 injected dylibs already fill the Mach-O header slack, so the extra command
spilled past file offset 0x4000 into `__text` and the app died at launch with
`EXC_BAD_INSTRUCTION` inside `dyld4::...notifyObjCInit` (crash log of 2026-10-19,
`pc` pointed at the text `@rpath/YTweaks.dylib` at offset 0x4000). Any solution
must therefore add **no** injected dylib.

## Goal
In IPAs built from this fork, the YouTube wordmark in the header shows the
"DavidTube" logo. No tweak is removed or added; nothing else changes. The
change survives merges from upstream (`mrdrvt99/YouProEXTRA`).

## Non-goals
App icon, display name, Shorts/Music/Kids logos, any runtime hook.

## Facts about the target (YouTube 21.41.5 IPA, inspected 2026-10-19)
- Logos live in `Payload/YouTube.app/Innertube_Resources.bundle/Assets.car` (BOM container, 2.4 MB, 612 facets). There are no loose PNGs.
- Facets: `youtube_logo`, `youtube_logo_dark`, `youtube_logo_cairo`, `youtube_logo_dark_cairo`, `youtube_premium_logo`, `youtube_premium_logo_white`, `youtube_premium_logo_cairo`, `youtube_premium_logo_dark_cairo`. Which one the header uses is unknown, so all eight are patched.
- Sizes (px): `youtube_logo*` 122×48 @1x, 244×96 @2x, 366×144 @3x (61×24 pt); `youtube_premium_logo*` 129×48 / 258×96 / 387×144 (64.5×24 pt).
- Each of these renditions is a 330–334 byte CSI whose payload is an internal link (`INLK`, frame x/y/w/h) into a packed atlas rendition, not a bitmap. Pixel format of the link headers is BGRA.
- The CI runner is `macos-15` (has `assetutil`, Xcode, libcompression).

## Approach
A Python tool `davidtube/tools/patch_car.py` edits `Assets.car`, and
`davidtube/patch_ipa.sh` wraps it for the workflow:
1. Unzip `Assets.car` from the IPA, parse the BOM (block index, `FACETKEYS`, `KEYFORMAT`, `RENDITIONS` tree).
2. For each target facet and each scale (24 renditions: 8 facets × @1x/@2x/@3x), take the existing link CSI and replace it with a **standalone image CSI** carrying DavidTube pixels. The atlas renditions (compression type 11, Apple's proprietary DeepMap2, which cannot be re-encoded) are never touched.
3. The standalone CSI is built from a template: an existing non-linked BGRA image rendition of the same catalog provides the header/info-list layout; width, height, scale and name are set for the target; the payload is a `CELM` block, compression type 4 (LZFSE, written as uncompressed LZFSE `bvx-` blocks so no compressor is needed), chunked `height/3` rows with a row stride of `ceil32(width*4)` (as in every real LZFSE rendition of the catalog, entry 1007 of the info list), pixels premultiplied BGRA, sized exactly as the original link CSI's width × height. The rendition name is copied verbatim from the original link CSI.
4. The new CSI bytes are appended to the end of the file and the target's block-index entry (address, length) is updated. The RENDITIONS and FACETKEYS trees, the key format and every other block stay byte-identical.
5. Variant: `*_dark*` and `*_white` facets get the white-text logo; the others get the `#111111`-text logo. The logo is contain-fit and centered on a transparent canvas of the original rendition's size.
6. Write the patched `Assets.car` back into the IPA.
One step in `.github/workflows/buildyoupro.yml`, before `Inject Tweaks Into IPA`, runs the script. It can be added to `buildnoylite.yml` and `buildcustom.yml` later (one line each).

## Safety (a corrupt catalog crashes the app at launch)
- The tool re-parses its own output and checks: same block count, every untouched block byte-identical, all 612 facets still present, patched renditions decode (LZFSE) to the expected pixels.
- On the macOS runner it also runs `assetutil --info` on the patched catalog and compares the facet/rendition listing with the original; any difference outside the patched facets fails the check.
- If any check fails, the step emits `::warning::` and leaves the IPA untouched; the build still succeeds (without the logo). A broken catalog is never shipped.
- If the facet names are not found (YouTube renamed them), the step warns and does nothing.

## Fork-safety
New files only under `davidtube/` and `docs/superpowers/`. Upstream files touched: `buildyoupro.yml` (one step, a few lines) and an appended README note.

## Verification
- Unit tests on a small synthetic BOM/CAR fixture built by the test itself (no copyrighted catalog committed): round-trip, patch, untouched-block identity.
- The tool is run against the real 21.41.5 catalog; the owner runs `assetutil --info` on original vs patched catalogs on their Mac and installs the IPA on the iPhone (dark and light mode).

## Risks / open items
- The exact pixel byte order/premultiplication and info-list contents of a standalone rendition are taken from a template rendition of the real catalog (plan task 2) and are validated by `assetutil --info` and on device; an unconfirmed detail is a reason for the validation to fail (logo not applied), never for the patched catalog to ship.
- Visual: the slot is 61×24 pt (ratio 2.5:1) but the DavidTube logo is 3.65:1, so a contain-fit makes it ~17 pt tall; the avatar may be small. Judged by the owner on device; a text-only or cropped variant is the fallback.
- A future YouTube may move the logos out of this catalog or change the packing; failure mode is "original logo", never a crash.

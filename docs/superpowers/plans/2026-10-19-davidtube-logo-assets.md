# DavidTube Logo via Assets.car Patch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** IPAs built by `buildyoupro.yml` show the "DavidTube" logo in the header, with no extra injected dylib and no other change.

**Architecture:** `davidtube/tools/` holds a small Python toolkit: `car.py` (read/modify a BOM `Assets.car`), `csi.py` (build a standalone image rendition from a template), `render.py` (draw the logo at a given pixel size), `patch_car.py` (orchestrate + validate + fall back). `patch_ipa.sh` runs it on `youtube.ipa` before cyan injection. A CI-side check uses `assetutil` on macOS.

**Tech Stack:** Python 3 (stdlib `struct`, `zlib`, `zipfile`; Pillow for drawing), POSIX sh, GitHub Actions (`macos-15`), `assetutil`.

**Spec:** `docs/superpowers/specs/2026-10-19-davidtube-logo-assets-design.md`

## Global Constraints

- No injected dylib/tweak, no `.deb`, no hook (the Mach-O header has no slack; see spec).
- Only upstream files touched: `.github/workflows/buildyoupro.yml` (one step) and `README.md` (appended note). Everything else under `davidtube/` and `docs/superpowers/`.
- Target facets (exact names): `youtube_logo`, `youtube_logo_dark`, `youtube_logo_cairo`, `youtube_logo_dark_cairo`, `youtube_premium_logo`, `youtube_premium_logo_white`, `youtube_premium_logo_cairo`, `youtube_premium_logo_dark_cairo`; scales 1x, 2x, 3x (rendition key attribute 12 = scale; identifier attribute 17; key attributes order from `KEYFORMAT`: `(7,13,12,15,16,8,17,1,2)` in the 21.41.5 catalog, always read from the file).
- Variant: names containing `dark` or ending `_white` → white-text logo (`davidtube_fundo_escuro.svg`); all others → `#111111`-text logo (`davidtube_fundo_claro.svg`).
- Output renditions are exactly the original link rendition's `width × height` pixels (e.g. `youtube_logo` 122×48 / 244×96 / 366×144; `youtube_premium_logo*` 129×48 / 258×96 / 387×144), BGRA, transparent background, logo contain-fit and centered.
- BOM and CAR parsing: BOM container fields are big-endian; CAR/CSI/KEYFORMAT/facet-token fields are little-endian; tree leaves are reached by descending to the first leaf and following `forward` links.
- Standalone renditions use CELM compression type 4 (LZFSE as uncompressed `bvx-` blocks), chunks of height/3 rows, row stride ceil32(width*4) — evidence-based deviation from the original ZIP idea (no type 0/2 exists in the real catalogs); the rendition name is copied verbatim from the original link CSI (e.g. `youtube_logo.png` at 1x, `youtube_logo@2x.png` at 2x).
- Untouched blocks stay byte-identical; patched blocks are appended at the end of the file and the block-index entry updated.
- Fail-safe: any parse/validation error → output IPA is the unmodified input, `::warning::` printed, exit code 0. Never ship an unvalidated catalog.
- Python is run as `python3 -I`; tests as `python3 -m unittest discover -s davidtube/tests` from the repo root.
- Do not commit any file extracted from the YouTube IPA.

## Review Focus

- Facet name missing (renamed in a future YouTube) → warn, IPA untouched, exit 0.
- Catalog already patched (second run) → idempotent, no corruption.
- Input IPA without `Innertube_Resources.bundle/Assets.car` → warn, untouched.
- A target rendition that is not a link (already standalone) → still replaced correctly using its own dimensions.
- Partial failure mid-way (e.g. 23 of 24 renditions OK) → nothing shipped (all-or-nothing).

---

### Task 1: BOM/CAR reader and block patcher (`car.py`)

**Files:**
- Create: `davidtube/tools/car.py`
- Test: `davidtube/tests/test_car.py`, `davidtube/tests/fixtures.py` (builds a tiny synthetic BOM catalog in memory: 3 facets, 2 trees with ≥2 leaf nodes linked by `forward`, a `KEYFORMAT`, a few CSI blobs)

**Interfaces:**
- Produces: `class Car` with
  - `Car(data: bytes)`; raises `CarError` on malformed input.
  - `facets() -> dict[str, dict[int, int]]` (facet name → attribute map; identifier is key 17).
  - `renditions() -> list[Rendition]` where `Rendition` is a dataclass `(attrs: dict[int,int], key_block: int, value_block: int)`.
  - `block(i: int) -> bytes`; `replace_block(i: int, data: bytes) -> None` (append to the end of the file buffer, update the index entry).
  - `to_bytes() -> bytes`; `block_count() -> int`.
- Produces: `class CarError(Exception)`.

- [ ] **Step 1: Write failing tests** in `test_car.py`: parse the synthetic catalog and assert facet names/ids and rendition attrs (including a leaf reached only via `forward`); `replace_block` then `to_bytes()` re-parses with the new data for that block, all other blocks identical, `block_count()` unchanged; truncated data and wrong magic raise `CarError`.
- [ ] **Step 2: Run** `python3 -m unittest davidtube.tests.test_car -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `car.py` per the Global Constraints (endianness, leaf walking). `replace_block` appends the new bytes at the current end of file and rewrites that entry's `(address, length)` in the big-endian index table; the index table and vars stay where they are.
- [ ] **Step 4: Run** → PASS. Also add a test skipped unless env `DAVIDTUBE_REAL_CAR` points to a catalog: it asserts 612 facets / 1866 renditions and that all 8 target facets exist (for the owner/CI to run on the real file).
- [ ] **Step 5: Commit** `feat(davidtube): BOM/CAR reader`.

### Task 2: Standalone image rendition builder (`csi.py`)

**Files:**
- Create: `davidtube/tools/csi.py`
- Test: `davidtube/tests/test_csi.py`

**Interfaces:**
- Consumes: `Car` (Task 1) only in the integration test with the real catalog (skipped without `DAVIDTUBE_REAL_CAR`).
- Produces: `parse_csi_header(csi: bytes) -> CsiHeader` (dataclass: `width, height, scale100, pixel_format: bytes, name: str, info_length: int, payload_kind: bytes` where `payload_kind` is `b'INLK'` or `b'CELM'`); `build_image_csi(template: bytes, name: str, width: int, height: int, scale100: int, bgra: bytes) -> bytes`; `find_template(car: Car) -> bytes` (first rendition whose payload is `CELM` with compression type 2 or 0 and pixel format `BGRA`; falls back to constructing none and raising `CarError`).

- [ ] **Step 1: Write failing tests**: with a hand-built template CSI (header `ISTC`, version 1, 188-byte fixed part, an info list with the slice/metrics/composition/bitmap-info entries, `CELM` payload), assert `build_image_csi(...)` returns a blob whose parsed header has the requested width/height/scale/name, whose `CELM` payload decompresses with `zlib` to exactly `width*height*4` bytes equal to the input, and whose recorded payload size, info-list length and slice/metrics sizes are self-consistent. Name longer than 127 bytes → `ValueError`; `len(bgra) != width*height*4` → `ValueError`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `csi.py`. Header field offsets (little-endian): tag@0, version@4, flags@8, width@12, height@16, scale@20, pixelFormat@24, colorSpace@28, name@44 (128 bytes), infoListLength@168, bitmapCount@172, payloadSize@180, info list @184 (`infoListLength` bytes), then the `CELM` payload (`'CELM'`, version 0, compression type 2, data length, zlib data). Copy the template's info list, rewriting only the width/height/scale-dependent entries; for the rendition-name field use `"<name>@<n>x.png"` like the originals (e.g. `youtube_logo@2x.png`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(davidtube): standalone CSI builder`.

### Task 3: Logo renderer for arbitrary rendition sizes (`render.py`)

**Files:**
- Create: `davidtube/tools/render.py`; Modify: `davidtube/tools/make_logos.py` only if it must expose `compose(svg)` (otherwise import it as-is)
- Test: `davidtube/tests/test_render.py`

**Interfaces:**
- Consumes: `make_logos.compose(svg: str) -> PIL.Image` (existing, returns the cropped 1387×380 supersampled RGBA).
- Produces: `render_logo(variant: str, width: int, height: int) -> bytes` (`variant` is `"dark"` or `"light"`; returns premultiplied BGRA, length `width*height*4`; logo contain-fit and centered on a transparent canvas).

- [ ] **Step 1: Write failing tests**: output length equals `w*h*4`; corner pixel alpha 0; for `244×96` the logo's non-transparent bounding box fits inside the canvas, is horizontally centered (±1 px), and its aspect ratio is within 2% of 3.65; dark variant has opaque text pixels `(255,255,255)`-ish and light variant `(17,17,17)`-ish in the right 70% of the bbox; premultiplication check: for every pixel `B,G,R <= A`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `render_logo` using `make_logos.compose` on the SVG in `davidtube/source/`, LANCZOS resize, paste, convert to premultiplied BGRA.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(davidtube): logo renderer`.

### Task 4: Patch orchestrator (`patch_car.py`)

**Files:**
- Create: `davidtube/tools/patch_car.py`
- Test: `davidtube/tests/test_patch.py` (synthetic catalog from `fixtures.py` extended with 2 target facets × 3 scales as link renditions, plus a template rendition; and a synthetic IPA zip containing `Payload/YouTube.app/Innertube_Resources.bundle/Assets.car`)

**Interfaces:**
- Consumes: `Car`, `CarError` (Task 1); `build_image_csi`, `find_template`, `parse_csi_header` (Task 2); `render_logo` (Task 3).
- Produces: `TARGETS: tuple[str, ...]` (the 8 facet names); `variant_for(name: str) -> str`; `patch_catalog(data: bytes) -> bytes` (raises `CarError` if any target facet/rendition is missing or validation fails); `patch_ipa(ipa_in: str, ipa_out: str) -> bool` (returns True if patched, False if left untouched; never raises); CLI `python3 -I davidtube/tools/patch_car.py IN.ipa OUT.ipa` (exit code always 0; prints `::warning::` lines on fallback).

- [ ] **Step 1: Write failing tests**: `variant_for` for all 8 names (`youtube_logo`→light, `youtube_logo_dark_cairo`→dark, `youtube_premium_logo_white`→dark, `youtube_premium_logo_cairo`→light); `patch_catalog` on the synthetic car: every target rendition's CSI now has payload `CELM`, correct width/height from the original, all non-target blocks byte-identical, block count unchanged, running it twice gives a valid catalog; synthetic catalog missing one target facet → `CarError`; `patch_ipa` on a good IPA writes a patched IPA (other zip members byte-identical, same order) and returns True; IPA without the catalog, corrupt catalog, and missing-facet cases return False and the output file is a byte-identical copy of the input.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** per the spec: resolve facet name → identifier (attr 17), select renditions whose identifier matches, replace each value block with `build_image_csi(template, name, w, h, scale100, render_logo(...))` using the original CSI's width/height/scale/name stem; re-parse the result and verify (block count, untouched blocks, all targets decode). All-or-nothing.
- [ ] **Step 4: Run** → PASS (`python3 -m unittest discover -s davidtube/tests`).
- [ ] **Step 5: Commit** `feat(davidtube): Assets.car patcher with fail-safe`.

### Task 5: macOS validation, IPA wrapper and workflow step

**Files:**
- Create: `davidtube/tools/validate_car.py`, `davidtube/patch_ipa.sh`
- Modify: `.github/workflows/buildyoupro.yml` (insert one step directly before `Inject Tweaks Into IPA`); `README.md` (append a short "DavidTube logo" section: what it does, how to resync with upstream — the only expected conflict is the added step — and that failure leaves the original logo)
- Test: `davidtube/tests/test_validate.py` (the comparison logic only, with fake `assetutil` JSON)

**Interfaces:**
- Consumes: `patch_ipa` (Task 4).
- Produces: `validate_car.py ORIGINAL.car PATCHED.car` — runs `assetutil --info` on both (macOS only; if `assetutil` is absent, exits 0 and prints `::notice::assetutil unavailable`), compares the JSON listings and exits 1 unless the only differences are in the 24 target renditions (names, count, and every non-target entry identical); function `compare_listings(orig: list[dict], patched: list[dict], targets: set[str]) -> list[str]` returns the list of unexpected differences (empty = OK).
- Produces: `davidtube/patch_ipa.sh IPA` (POSIX sh): copies `IPA` to a temp, runs `patch_car.py IPA temp`, extracts both catalogs and runs `validate_car.py`; if validation fails keep the original; on success `mv` temp over `IPA`. Always exits 0.
- Produces: workflow step `Patch DavidTube logo into IPA`: `run: sh davidtube/patch_ipa.sh youtube.ipa` (needs `pip install pillow` first inside the script if Pillow is missing).

- [ ] **Step 1: Write failing tests** for `compare_listings`: identical lists → `[]`; a changed target entry → `[]`; a changed non-target entry, a removed entry, an added entry → non-empty list naming it.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `validate_car.py` and `patch_ipa.sh`; add the workflow step and README note. Verify YAML with `python3 -I -c "import yaml;yaml.safe_load(open('.github/workflows/buildyoupro.yml'))"`; `sh -n davidtube/patch_ipa.sh`.
- [ ] **Step 4: Run** all tests → PASS; run `git diff --stat fcf741f..HEAD -- . ':!davidtube' ':!docs'` → only `buildyoupro.yml` and `README.md`.
- [ ] **Step 5: Commit** `ci(davidtube): patch the logo into the IPA`.

### Task 6: Dry run on the real catalog and owner handoff

- [ ] **Step 1:** Download the owner's IPA (URL given in the conversation) into an empty scratch directory; extract `Assets.car`; run the skipped real-catalog tests with `DAVIDTUBE_REAL_CAR` set; run `patch_catalog` on it; assert 24 renditions replaced, 612 facets intact, untouched blocks identical. Do not commit any extracted file.
- [ ] **Step 2:** Produce `davidtube-sample/Assets.car.patched` and `Assets.car.original` in the scratchpad (not committed) and write `davidtube/MAC-TEST.md`: commands for the owner's Mac (`assetutil --info` on both, `diff`, run `patch_ipa.sh` on the IPA, install via SideStore, check dark and light mode, what a crash log would mean).
- [ ] **Step 3:** Push needs the owner's token (`Contents` + `Workflows` write); until then work stays local on branch `davidtube-logo-assets`.

## Self-Review

- Spec coverage: reader/patcher (T1), standalone CSI from template (T2), contain-fit variants (T3), 24 renditions all-or-nothing + fallback (T4), `assetutil` validation + workflow + README (T5), real-catalog dry run + Mac handoff (T6). Facets sharing atlas rectangles no longer matters (atlas untouched).
- Type consistency: `Car`, `CarError`, `build_image_csi`, `find_template`, `parse_csi_header`, `render_logo`, `patch_catalog`, `patch_ipa`, `variant_for`, `compare_listings` are named identically where consumed.
- Known unknown: exact info-list entries a standalone rendition needs; T2 copies them from a real template and T5/T6 validation + the owner's Mac check are the safety net.

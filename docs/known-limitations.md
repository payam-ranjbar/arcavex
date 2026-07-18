# Known limitations

Arcavex documents what it does **not** do as carefully as what it does. Nothing here is a bug to be
worked around silently — each item is either deferred by specification (§12, §7.4, Post-v1) or a
measured miss reported honestly. Where a limit has a diagnostic, it is a located error, not a silent
surprise. The forward-looking backlog is [backlog.md](backlog.md); measured performance is
[performance.md](performance.md).

## Deferred by specification

These are intentional v1 boundaries (spec §12 / §7.4), tracked in [backlog.md](backlog.md):

- **Vector-preserving PDF and CMYK / PDF-X prepress.** PDF output is **raster-embedded RGB** at the
  target DPI with correct physical page size and `TrimBox`/`BleedBox` (A4 + bleed is first-class), but
  text and shapes are rasterized pixels, not selectable vectors, and there is no CMYK/PDF-X color
  path.
- **GPU rendering backend.** Rendering is CPU raster (deterministic by design). No GPU backend.
- **Hostile-extension isolation / WASM runtime.** A Python extension is trusted local code and is not
  sandboxed; a deliberately-malicious enabled extension is out of scope for v1. A WASM- or OS-isolated
  worker runtime may come later if third-party distribution requires it. See
  [extension-guide.md](extension-guide.md#trust-boundary--read-this-first).
- **Animation / video.** Still images and PDF only.
- **Hosted-service concerns** (accounts, tenants, quotas) and a **SQLite discovery index** (files stay
  canonical).
- **Automatic install of older engine versions** for compatibility reruns, and **hyphenation**.

## Authoring features not yet available

Each of these is a *located* diagnostic, so you learn the boundary at authoring time rather than
getting silently-wrong output:

- **`fit_content` is text-only.** Sizing an image or group to its intrinsic content is not available
  (`ARC-LAY-020`); give those nodes an explicit size or an `aspect` ratio.
- **Wrapping stacks are deferred.** A stack with `wrap: true` reports `ARC-LAY-056` rather than faking
  multi-row flow; lay wrapped rows out with nested stacks for now.
- **`line_height` is not yet honored.** The bundled text stack (skia-python 144) exposes no strut
  height override, so setting `line_height` is a located `ARC-TPL-053`. Tracked for a later phase
  ([ADR-0001](adr/0001-skia-python-144-platform-baseline.md)).

## Text metrics are paragraph-level

skia-python 144 exposes no per-line/per-glyph boxes ([ADR-0001](adr/0001-skia-python-144-platform-baseline.md)),
so `max_lines` is approximated by dividing the measured paragraph height by a *measured* single-line
height (not an invented constant) — exact for uniform text — and layout inspection reports paragraph
bounds and baseline rather than per-glyph rectangles. Fit policies, BiDi/RTL, and locale digits are
implemented in the Arcavex text service on top of the scalar metrics the binding does expose, so the
public template contract is unaffected.

## Asset store is minimal

The content-addressed store ingests assets by hash with sidecar metadata and enforces decode guards
(max source bytes, max decoded pixels, format allowlist) against the image header *before* any decode.
The derived-variant LRU cache (a large source downscaled once into the slot it occupies, under a byte
budget, at `$ARCAVEX_HOME/cache/derived/`) shipped in this build. This is enough to pin assets in run
manifests; a richer asset manager is future work.

## Provenance is same-platform

A `rerun` reproduces byte-identical output on the same engine version and platform (OS/arch);
cross-platform reproduction is **perceptual, not bit-exact** (sub-pixel AA and font rasterization
differ across platforms). `rerun` refuses to claim exact reproduction when the engine version or
platform differs, and golden images are compared perceptually (DSSIM ≤ 0.003) with a per-platform
committed set — see [testing.md](testing.md#golden-images-per-platform-sets).

## Platform baseline

- **Reference platform:** Windows 11 x86-64, CPython 3.12, skia-python 144. The committed golden set
  is `win-x86_64`, validated locally.
- **ARM64 (linux-aarch64 / macos-arm64)** wheels exist upstream but were not testable on the Windows
  x86-64 development machine; CI is the verification point, ARM64 carries relaxed (2×) performance
  expectations, and its golden set is bootstrapped by review — recorded as a known limitation, not
  silently claimed ([ADR-0001](adr/0001-skia-python-144-platform-baseline.md),
  [testing.md](testing.md#ci-matrix)).

## Performance misses (measured)

[performance.md](performance.md) records honestly, with real numbers, where the spec §8.2 p95 targets
are missed. The base pipeline is well inside budget (plain A4 @ 300 ≈ 0.8 s, plain 1080×1350 ≈ 0.13 s,
compile ≈ 13 ms p95, peak RSS ≈ 1.13 GiB), but:

- **Raster-effect-heavy renders miss.** Each raster effect pays a full `skia.Image → ndarray →
  skia.Image` round-trip, so a 3-raster 1080 scene is ≈ 2.2 s (target ≤ 1.5 s) and a 4-deep A4 @ 300
  chain ≈ 18 s (target ≤ 6 s). Fusing consecutive raster passes / a shared mutable buffer is the
  tracked fix.
- **CLI cold start ≈ 1 s** (target ≤ 400 ms), dominated by the one-time `skia-python` import and
  font-database build. Long-lived processes (MCP server, `preview --watch`) pay it once and then
  render at the warm numbers.

## RTL / bidi approach

Base paragraph direction is controlled with Unicode BiDi isolates (LRI/RLI/PDI) emitted by the text
service around paragraph text, plus logical `start`/`end` alignment mapped to left/right by the
resolved direction — because skia-python 144 exposes no `setTextDirection`
([ADR-0001](adr/0001-skia-python-144-platform-baseline.md)). Authors keep writing plain
`direction: rtl`; the isolate handling is internal. Embedded LTR runs inside an RTL composition
(English names, venue) shape correctly, as the reference poster demonstrates.

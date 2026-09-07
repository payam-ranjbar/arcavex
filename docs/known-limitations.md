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
- **Skia announces a missing ICU data file that it then finds anyway.** On Windows, where the data
  file ships inside `skia-python`, an install whose base interpreter has no `icudtl.dat` beside it
  — a freshly downloaded managed Python, typically —
  Skia's loader prints `SkIcuLoader: datafile missing: …` to stderr on every command before
  falling back to the copy inside `skia-python`. Nothing is broken: `doctor` reports `icu ok` and
  explains the line, with the copy-one-file remedy. The message comes from the library's C++ layer,
  so no Python-level filter can suppress it. [Install notes](install.md#icu-icudtldat).

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

## Overlap reporting is per-group

`layout inspect` enumerates overlapping pairs **within each group**. Two nodes in different groups
are never compared, however much they intersect — on the reference poster that is 20-22 unreported
intersecting pairs per format. A clean `overlaps` list therefore means "no sibling collisions",
not "nothing on this canvas collides".

Nearly all of those unreported pairs are legitimate layering (a background under everything, a card
panel under its own labels), which is why widening the scope is a redesign of the containment rule
rather than an enumeration change; the measured trade-off is in [backlog.md](backlog.md). If you
need a whole-canvas guarantee today, compare `bounds_pt` across the tree yourself — `layout inspect
--json` reports every node's box.

## Validation checks geometry, not design

This is the largest boundary in the engine, and the one most easily mistaken for a defect.

Arcavex validates that a design is **well-formed**: constraints resolve, text fits its box, line
caps hold, unknown fields are rejected, assets exist and decode, effects and locales are declared.
`layout inspect` goes further and reports resolved geometry — overlaps, overflow states, shrink
outcomes — which is what makes the engine usable by an author who cannot see the render.

It does **not** evaluate whether a design is any good, and it never will. During the authoring
session behind [public-readiness-fix-list.md](public-readiness-fix-list.md), across four full
design revisions, every design judgement came from a human or a model *looking at the pixels*:
dead zones in the composition, a 4px offset echo reading as an unintended bevel, a logo too small
to read at feed scale, page grain too loud, a Farsi line floating with no edge relationship. The
engine reported clean validation for every one of those drafts, including the ones that were
rejected outright. That is correct behaviour — none of them were malformed.

So: **a clean validation means the design is buildable, not that it is good.** If you are driving
Arcavex from an agent, treat `validate` and `layout inspect` as the compiler, not the reviewer.
Something has to look at the image.

Design judgement is a layer above this one and probably a separate product that consumes it —
building taste into the renderer would compromise the determinism that makes the renderer worth
having. What could reasonably be added here later is a narrow `audit` command limited to checks
that are objective and testable rather than matters of taste: WCAG contrast per text node against
its resolved backdrop, minimum rendered cap-height at a declared viewing scale, declared
safe-area assertions per format, optical-margin deviation between text left edges in a column.
Anything past that becomes opinion, and opinion does not belong in a deterministic engine. It is
in [backlog.md](backlog.md); nothing about it is committed.

The one deliberate exception is `ARC-AST-020`, which warns when `fit: contain`/`cover` is about to
scale mostly transparent padding. It survives the rule above because the measurement is objective
(opaque area over canvas area) and the failure is otherwise undetectable from inside the engine —
a correct render that is silently useless.

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

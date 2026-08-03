# Changelog

All notable changes to Arcavex are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning for both
the engine and the IR schema.

## [Unreleased]

### Added

- **`SiblingOverlap.kind` on `layout inspect`** — every reported overlap is now classified as
  `content` (the nodes' layout bounds genuinely intersect) or `halo` (only their effect-grown
  paint bounds do, i.e. a shadow, glow or torn-paper edge reaching over a neighbour). Overlap
  reporting previously compared `paint_bounds` alone, so a shadowed node was indistinguishable
  from a real collision and the useful signal got filtered away with the noise. The field is
  carried by `--json` and by the `arcavex_layout_inspect` MCP tool, so an agent that cannot see
  the render filters structurally instead of guessing.

### Changed

- **`layout inspect` human output** groups overlaps: `content` ones are listed under the
  `overlaps` heading, `halo` ones demoted to a dimmed *effect spill* subsection, with a
  `N content, M effect spill` count on the heading itself.
- **`layout inspect` prints both boxes per node** — `bounds` (the resolved layout box) and
  `paint` (that box grown by rotation and effect expansion). Only `bounds` was shown before,
  which is why a halo overlap's rect looked like it came from nowhere.
- **`rect_pt` on a `content` overlap is now the content intersection**, not the paint
  intersection — so its width/height is the actual collision depth to correct. `halo` overlaps
  still report the paint intersection, which is the only one that exists for them.
- **The full-bleed backdrop suppression threshold** (a node covering ≥90% of its parent region is
  structure, not a collision) is measured on the layout box rather than the paint box, so a
  generous shadow can no longer promote an ordinary node into a backdrop and have its containment
  of a sibling silently dropped.

### Compatibility

`SiblingOverlap.kind` is **additive and forward-compatible**: it defaults to `content`, so a
payload serialised before the field existed still parses and a consumer that ignores the field is
unaffected. `response_version` therefore stays at `1` and no migration is required. Consumers that
want the new signal opt in by reading `kind`; the recommended filter for "real problems only" is
`kind == "content"`. Which node pairs are reported is unchanged — verified byte-for-byte against
the previous output across all 16 reference-poster and IPEN format × locale targets; the change is
purely the added label plus the more precise `rect_pt` for content overlaps.

## [0.1.0] — 2026-07-15

First tagged release: a local-first, headless, deterministic, template-driven rendering engine.
Same inputs produce byte-identical outputs across every supported format.

### Added — Phase 7 (export and release hardening)

- **JPEG and WebP exporters** with quality/lossless control in `ExportOptions`. Lossy quality
  defaults to 90 (the conventional "visually lossless, small" setting) when `--quality` is omitted.
  Lossless WebP is bit-exact (VP8L), not approximated. JPEG flattens transparency over opaque white
  deterministically.
- **Raster-embedded RGB PDF exporter** (`-o out.pdf`) at the target DPI with the correct physical
  page size and `TrimBox`/`BleedBox` (A4 + bleed is first-class). The embedded raster is stored at
  full render resolution. Vector-preserving PDF and CMYK/PDF-X remain future work.
- **Exporter selection by output extension** — `.png`, `.jpg`/`.jpeg`, `.webp`, `.pdf`. New CLI
  flags `--quality` and `--lossless`.
- **Format determinism** extended to every exporter: identical inputs produce byte-identical
  JPEG/WebP/PDF. Exported files embed only stable metadata (engine version, render signature, color
  policy) — never timestamps or run ids.
- **Derived-asset LRU cache** (`$ARCAVEX_HOME/cache/derived/`): a large image drawn into a small
  slot is decoded and downscaled once, keyed by `(content-hash, target-size)` under a configurable
  byte budget. Both the in-memory and the on-disk tier are held under the byte budget, evicting the
  least-recently-used variant when over it. Disposable and never authoritative — a cold cache
  produces byte-identical output.
- **Per-render resource budgets** (`ARC-RND-020..023`): output-dimension, decoded-pixel,
  surface-memory (pre-flight), and wall-clock limits, configurable via `[budgets]` in `config.toml`,
  refusing an oversized render with a located diagnostic and exit code 4.
- **Path/symlink traversal guard** for template-relative assets (`ARC-AST-004`).
- **Located export-write failures** (`ARC-EXP-001`): an unwritable or invalid output path (a parent
  that is a file, a read-only directory, a full disk) reports as an actionable, located diagnostic
  with exit 1, instead of leaking as an internal engine error.
- **`arcavex doctor`** now self-tests the exporters (PNG/JPEG/WebP/PDF) and reports the derived
  cache directory and budget.
- **Packaged installation**: the wheel ships the bundled fonts (`arcavex/_bundled/fonts`); a clean
  install renders the quick-start without the dev tree.
- **CI workflow** (`.github/workflows/ci.yml`) for the linux-x86_64 + macos-arm64 + linux-aarch64
  matrix, plus a packaged-install job.
- **Documentation**: `docs/performance.md` (measured actuals), `docs/testing.md` (per-platform
  golden strategy), and a benchmark harness (`scripts/benchmark.py`).

### Added — earlier phases (0–6)

- **Phase 0–1**: pure kernel + SPI contracts, registry, Skia backend, anchor layout solver, PNG
  export, the template compiler, expression evaluator, and the diagnostic system.
- **Phase 2**: layout (stacks, anchors), the SkParagraph text stack (shaping, BiDi, RTL, fit
  policies), locales, masks, rotation, and layout inspection.
- **Phase 3**: the effect engine (geometry/color/raster/composite categories with fusion), shape
  generators, and style packs.
- **Phase 4**: the content-addressed asset store with decode guards.
- **Phase 5**: projects, the versioned library, run manifests, rerun/diff provenance, and the MCP
  authoring surface.
- **Phase 6**: the trusted-local extension SDK, loader, and golden harness.

### Determinism guarantees

- Rendering confined to bundled fonts; no system-font fallback.
- All randomness flows from a seeded per-effect RNG.
- Atomic writes (temp file + rename) for every output; interrupted renders publish nothing.
- Immutable completed run directories; timestamps and run ids live only in manifests.

[0.1.0]: https://example.com/arcavex/releases/0.1.0

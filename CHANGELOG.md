# Changelog

All notable changes to Arcavex are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning for both
the engine and the IR schema.

## [Unreleased]

### Changed — **breaking**: unknown fields are now rejected in every authoring scope

Arcavex promised that "unknown fields are rejected rather than silently ignored, so a misspelled
property cannot quietly do nothing." That held only for a handful of node sub-blocks. At the
template root, in `formats`, in a `canvas`, in a variable declaration, on a **node top level**, and
in an `effects[]` entry, an invented field validated clean and did nothing.

That is the worst possible failure for a template language meant to be authored by an AI agent: the
engine answered `OK template is valid`, so the author kept building on a field that was inert. In
the case that prompted this, an agent invented `condition:` on nodes, shipped three nodes relying on
it, and wrote the invented behaviour into handoff documentation as a real engine constraint.
Deleting every `condition:` line produced a byte-identical render.

**This is a breaking change for any template carrying a junk field — and it is the fix for fields
that quietly did nothing.** A template that validates now has no inert lines in it. If a template
starts failing, the reported field was never doing anything; delete it, or move it to the scope the
hint names. No template shipped in this repository needed a change.

- **Five new diagnostics**: `ARC-TPL-064` (unknown node field), `ARC-TPL-065` (template root),
  `ARC-TPL-066` (format / canvas), `ARC-TPL-067` (variable declaration), `ARC-TPL-068` (effect
  entry). `ARC-TPL-051` now also covers the `transform`, `mask`, `padding`, and `repeat`/`if`
  construct mappings, which were permissive too.
- **`ARC-TPL-064` names the real home of a wrong-scope field** instead of only rejecting it. There
  is no per-node `condition:` (the hint points at the structural `if:` / `node:` construct);
  `opacity`/`color`/`font_size` belong in `style`; `width`/`height` in `constraints.size`; `x`/`y`
  in `constraints.anchor`; `rotation` in `transform`. A field that is real but belongs to another
  node kind is told which kind owns it.
- **Fields that are authored-but-deliberately-unsupported keep their own, more useful diagnostic**:
  `line_height` still reports `ARC-TPL-053` and a stack's `wrap` still reports `ARC-LAY-056`.
- A guard test walks the whole authoring surface and asserts every scope rejects an unknown key, so
  a scope added later cannot silently reintroduce this.

### Fixed

- `make docs-diagnostics` no longer rewrites every generated file with CRLF on Windows (the
  declared reference platform), which made a one-entry edit look like a 118-file change. The
  previously CRLF-committed files are normalized to LF.

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

### Added

- **`arcavex font` command group** — the supported way to use a typeface beyond the four bundled
  families, which previously required knowing (from prose in the docs) to drop a `.ttf` into
  `$ARCAVEX_HOME/fonts` by hand:
  - `font list [--json]` lists every resolvable family with its files, marks each **bundled** or
    **installed**, and names the directory `add` writes to — the answer `doctor` never gave, since
    it reported only the family *count*.
  - `font add PATH [--license PATH]` installs a `.ttf` into the Arcavex home and reports the family
    name **as the engine resolves it**, read from the file with the shaper's own resolver. A file
    stem and its internal family name routinely differ (`Lateef-Regular.ttf` provides `Lateef`) and
    `style.font` must name the family, so reporting the stem would hand back a name that does not
    render. `--license` copies a licence alongside the font, following the bundled OFL convention.
  - `font remove FAMILY` removes an installed family and its licence; a family bundled with the
    engine is refused (`ARC-RND-032`), because it backs the default font stacks.
- **`arcavex_font_list` MCP tool** — the legal `style.font` vocabulary is now discoverable by an
  agent alongside `arcavex_style_list`/`arcavex_effects_list`. Installing a font stays CLI-only, in
  the same class as `ext add`: an operator action on the machine, not an agent one.
- **New diagnostics** `ARC-RND-030`..`ARC-RND-034` for the font store (file not found, unusable
  typeface, bundled-family removal refused, no such installed family, unreadable/unwritable store).

### Changed

- **`ARC-RND-010` (font family not available)** now lists the **nearest** available families ahead
  of the full list and names `arcavex font add` in its hint, so a typo and a genuinely missing
  typeface get different, actionable answers. Its catalog entry no longer implies the font set is
  closed.

### Fixed

- **Fonts in the default Arcavex home were silently ignored.** Font discovery read `$ARCAVEX_HOME`
  directly and skipped the `~/.arcavex` default that `doctor` reports, so with `ARCAVEX_HOME` unset
  a font placed in `~/.arcavex/fonts` was never registered. Discovery now resolves through
  `fsutil.home_dir()` — the same single source of truth every other reader uses.

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

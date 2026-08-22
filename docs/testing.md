# Testing strategy

Arcavex's correctness contract is *determinism*: the same inputs produce byte-identical outputs.
The test suite is layered to prove that cheaply where it can and perceptually where it must, and
to keep the public contracts (JSON schemas, exit codes, diagnostic codes) from drifting. This
document describes how each layer works and, in particular, the per-platform golden-image strategy
and the CI matrix (spec §8.5).

## Layers

| Layer | Method | Where |
|---|---|---|
| Units, expressions, unit conversions | pytest + property-based (hypothesis) | `tests/unit/` |
| Layout | JSON bounds snapshots (cross-platform, deterministic) | `tests/unit/test_inspect_layout.py`, `test_layout*.py` |
| Rendering | Golden images, perceptual diff (dssim ≤ 0.003) | `tests/golden/` |
| Effects | GoldenHarness fixtures incl. bounds-expansion honesty | `tests/golden/`, `tests/unit/test_effects.py` |
| Exporters | Format validity + byte-identical determinism | `tests/unit/test_export_formats.py` |
| Derived cache | Cold==warm identity + LRU eviction | `tests/unit/test_derived_cache.py` |
| Resource budgets | Pre-flight refusal + located diagnostics + exit 4 | `tests/unit/test_budgets.py` |
| File safety | Path traversal, malformed asset, atomic/interrupted writes | `tests/unit/test_file_safety.py` |
| CLI DX | Tested command transcripts, JSON output, exit codes | `tests/e2e/` |
| Agent dogfood | Scripted MCP sessions | `tests/mcp_sessions/` |
| Semantic editing | Command execution, revision guard, rollback, on-disk history | `tests/unit/editor/` |
| Multi-process editing | Real concurrent processes over one project: locks, conflicts, no corruption | `tests/e2e/test_editor_races.py`, `test_editor_cli.py`, `test_editor_external_collaboration.py` |
| Desktop workbench | Component, accessibility, and browser end-to-end | `apps/desktop/src/**/*.test.tsx`, `apps/desktop/e2e/` |
| Packaged desktop | Installed build renders, restarts its engine, edits, and undoes to the original bytes | `scripts/verify_desktop_bundle.ps1` |

## Determinism: byte-identical across formats

Every exporter is tested for byte-identical reruns (`test_export_formats.py`): PNG, JPEG, WebP,
and PDF each render twice and compare `content_sha256`. Exported files carry **no** timestamps or
run ids — the PDF test asserts the absence of `/CreationDate`, `/ModDate`, and `/ID`, and that only
stable metadata (engine version as `/Producer`, the render signature, the sRGB color policy) is
embedded. Timestamps and run ids live only in run manifests, never in image bytes (spec §4.6).

The derived-asset cache is held to the same bar: a cold cache must produce byte-identical output to
a warm one (`test_render_is_identical_cold_vs_warm`). Two independent cold caches downscaling the
same source must agree bit-for-bit.

## Golden images: per-platform sets

Sub-pixel anti-aliasing and font rasterization differ across platforms, so golden images are
compared **perceptually** (DSSIM ≤ 0.003, i.e. SSIM ≥ 0.994), not byte-for-byte, and each platform
keeps its own committed set under `tests/golden/goldens/<platform-tag>/`. The platform tag is
`<os>-<arch>` — `win-x86_64`, `linux-x86_64`, `macos-arm64`, `linux-aarch64` — matching
`services.runs.platform_tag()`.

- The committed set in this repository is `win-x86_64` (the Phase 7 development platform), validated
  locally.
- On CI, a platform whose golden set is committed is compared strictly; a platform whose set is not
  yet committed uploads its renders as an artifact for review rather than failing the build (see
  `.github/workflows/ci.yml`), so a new platform is bootstrapped by reviewing and committing its
  first golden set.
- Regenerate goldens with `make golden-update` (sets `ARCAVEX_UPDATE_GOLDENS=1`) and review the
  image diff before committing. Never commit a golden update without looking at the diff.

The three end-to-end golden cases exercise the full pipeline: (1) the hardcoded hello-poster, (2)
the IPEN bilingual poster (fa/en, shaping + BiDi + RTL + masks + rotation), and (3) the pop-art
Warhol grid (shaders, loops, style packs).

## CI matrix

The intended matrix is **linux-x86_64 + macos-arm64 + linux-aarch64** (spec §8.5: aarch64 added in
Phase 7). Each job runs, in order: `ruff` lint, `mypy --strict` on the kernel, the import-linter
architecture contracts, the full test suite (excluding platform goldens), then the per-platform
golden comparison. A separate `packaged-install` job builds the wheel, installs it into a clean
throwaway venv, and renders the quick-start from that install — proving the package ships fonts and
resolves ICU without the dev tree (spec §8.5). ARM64 targets carry relaxed (2×) performance
expectations and are a supported build target, not a primary optimization goal.

The workflow file is written to be correct for CI even though the Phase 7 implementation validated
it on Windows locally; the Windows dev environment is not part of the published matrix but its
golden set is the committed reference.

## Public-contract snapshots

CLI JSON schemas, exit codes, template syntax, patch operations, and diagnostic codes are public
contracts (spec §9). Exit codes are asserted in `tests/e2e/`; every diagnostic code the engine can
emit must have a catalog entry and a matching `docs/diagnostics/<code>.md` file, enforced by
`tests/unit/test_explain.py`. Regenerate the diagnostic docs from the catalog with
`make docs-diagnostics`.

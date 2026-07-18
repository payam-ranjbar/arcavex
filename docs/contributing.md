# Contributing

Arcavex is developed against a technical design spec (`arcavex-technical-design-spec-v1.1.md`) with a
per-requirement status ledger (`IMPLEMENTATION_LEDGER.md`). This page covers the mechanics: dev
setup, the make targets, the test layers, the golden-update process, and how decisions are recorded.

## Dev setup

Python 3.11+ (reference: 3.12). Create a venv and install the dev extra (details in
[install.md](install.md)):

```bash
uv venv
uv pip install -e ".[dev]"
```

The `[dev]` extra adds `pytest`, `hypothesis`, `ruff`, `mypy`, `import-linter`, `pillow`, and `mcp`.
The console entry point is `arcavex` (`.venv/Scripts/arcavex.exe` on Windows,
`.venv/bin/arcavex` on POSIX). Run `arcavex doctor` to confirm the environment.

## Make targets

The `Makefile` uses `.venv/Scripts/python.exe` as `$(PY)`:

| Target | Runs |
|---|---|
| `make lint` | `ruff check src tests` |
| `make typecheck` | `mypy src/arcavex/kernel --strict` (the kernel is held to strict typing) |
| `make contracts` | `import-linter` — the [architecture layering contracts](architecture.md#the-import-linter-contracts) |
| `make test` | `pytest tests -q` |
| `make verify` | `lint typecheck contracts test` — the full release gate |
| `make golden-update` | regenerate per-platform goldens (`ARCAVEX_UPDATE_GOLDENS=1`) |
| `make docs-diagnostics` | regenerate `docs/diagnostics/*.md` from the catalog |
| `make bench` | run `scripts/benchmark.py` against the spec §8.2 targets |

Run `make verify` before proposing a change; it is the same gate CI enforces.

## Test layers

The suite is layered to prove determinism cheaply where it can and perceptually where it must — the
full description is [testing.md](testing.md). In brief:

| Layer | Where |
|---|---|
| Units, expressions, conversions (property-based) | `tests/unit/` |
| Layout (JSON bounds snapshots) | `tests/unit/test_inspect_layout.py`, `test_layout*.py` |
| Rendering (golden images, perceptual diff) | `tests/golden/` |
| Effects (GoldenHarness + bounds honesty) | `tests/golden/`, `tests/unit/test_effects.py` |
| Exporters (format validity + byte-identical determinism) | `tests/unit/test_export_formats.py` |
| Derived cache, budgets, file safety | `tests/unit/test_{derived_cache,budgets,file_safety}.py` |
| CLI DX (transcripts, JSON, exit codes) | `tests/e2e/` |
| Agent dogfood (scripted MCP sessions) | `tests/mcp_sessions/` |
| Packaged install (wheel in a clean venv) | `tests/e2e/test_packaged_install.py` |

Public contracts — CLI JSON schemas, exit codes, template syntax, patch operations, and diagnostic
codes — are snapshot-tested so they cannot drift (spec §9).

## Golden update process

Golden images are compared **perceptually** (DSSIM ≤ 0.003), and each platform keeps its own committed
set under `tests/golden/goldens/<platform-tag>/`. When a render legitimately changes:

1. Regenerate: `make golden-update` (sets `ARCAVEX_UPDATE_GOLDENS=1`).
2. **Review the image diff before committing.** Never commit a golden update without looking at the
   diff — the perceptual gate exists precisely so an unintended visual change is caught by eye.

A platform whose golden set is not yet committed uploads its renders as a CI artifact for review
rather than failing the build, so a new platform is bootstrapped by reviewing and committing its first
set. Details: [testing.md](testing.md#golden-images-per-platform-sets).

## Diagnostics are generated

Never hand-edit `docs/diagnostics/*.md`. The canonical catalog is
`src/arcavex/services/diagnostics_catalog.py` (one entry per code); the Markdown files are generated
with `make docs-diagnostics` and a test keeps them in sync. Add or change a diagnostic in the catalog,
regenerate, and a coverage test asserts every code the engine can emit has an entry. See
[diagnostics.md](diagnostics.md#single-source-of-truth).

## Architecture rules

Keep dependencies pointing inward (see [architecture.md](architecture.md)). The five import-linter
contracts are not advisory — `make contracts` fails a PR that, for example, makes the kernel import a
built-in or a client reach past `kernel.api`. New pluggable behavior goes behind an SPI contract and
is wired in `bootstrap.py`, not imported directly by a service.

## ADR process

Non-obvious, hard-to-reverse decisions are recorded as Architecture Decision Records under
[`docs/adr/`](adr/) (indexed in [adr/README.md](adr/README.md)). When a change adjudicates an
ambiguous semantic (as [ADR-0002](adr/0002-direction-inheritance-and-data-layering.md) did for
direction inheritance and data layering) or pins a platform constraint (as
[ADR-0001](adr/0001-skia-python-144-platform-baseline.md) did for the skia-python binding), add a
numbered ADR: context, decision, consequences. Reference it from the ledger row it satisfies.

## Documentation

Docs are Markdown under `docs/`, reachable from the [README docs index](../README.md#documentation)
within two clicks. Keep each doc's voice; verify any command you document by running it and pasting
real output — never fabricate. The [changelog](../CHANGELOG.md) is curated per release.

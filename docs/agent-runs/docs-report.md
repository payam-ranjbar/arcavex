# Docs consolidation report (task §12)

Consolidation pass over the per-phase docs: inventory, gap-fill, cross-link, make the set navigable
from `README.md`. Docs-only — no engine/source/test files were touched, and the test suite was not
run (only the documented commands + inventory greps). Nothing was committed.

## Coverage table

| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | `README.md` — overview, install/quick-start pointers, reference-poster showcase, docs index | **Updated** | Added a top-level Documentation index (14 rows, all ≤2 clicks), a reference-poster showcase with the 10-finals table (+ 2 A4 PDFs), and install/quick-start pointers. Collapsed the deep template-authoring reference and the inline "Known limitations" into concise summaries linking to the new `template-schema.md` / `known-limitations.md`; kept the command tables, config/budget tables, and MCP section (voice preserved). |
| 2 | `docs/install.md` | **Created** | From-source (uv/pip) + packaged wheel (links `packaged-install.md`, not duplicated), ICU note (ADR-0001), fonts, config home, and a `doctor` row-by-row table. |
| 3 | `docs/quick-start.md` | **Created** | 10-minute path: render → default-name → change data → new format → locale → export png/jpg/webp/pdf → `--resolved`/`explain`. Every transcript is real output. |
| 4 | `docs/tutorials/` | **Created** | Index + 3 tutorials: building a template from scratch (scaffold/nodes/constraints/stacks/fit), a bilingual template (reference-poster worked example), using+writing extensions (links `extension-guide.md`). |
| 5 | `docs/template-schema.md` | **Created** | Full authoring reference: sections, node kinds, constraints/anchors (incl. logical start/end), sizes, stacks, fit, units/colors, expressions + the 9-function table (from the `template_fns` registry), locales/data-layering, patch grammar, and the 15-effect table (from `effects list`). |
| 6 | `docs/cli.md` | **Created** | Every command with synopsis + key flags + a verified example. Built from the real `--help` tree for all top-level commands and all 9 subcommand groups. |
| 7 | `docs/diagnostics.md` | **Created (index)** | Indexes the existing generated `docs/diagnostics/<code>.md` set. Verified 142 catalog entries == 142 Markdown files (in sync). Per-family counts, exit-code mapping, and `explain` all from the code catalog. |
| 8 | `docs/extension-guide.md` | **Updated** | Verified current against the real `ext` CLI; added a concrete scaffold walkthrough (real `scaffold`/`validate`/`list` transcript). |
| 9 | `docs/architecture.md` | **Created** | Microkernel layer map (kernel/services/builtin/sdk/clients/bootstrap), document-state pipeline, the 8 SPI contracts table, the 5 import-linter contracts (from `pyproject.toml`), determinism + run/provenance models, MCP parity. |
| 10 | `docs/contributing.md` | **Created** | Dev setup, the 8 make targets (from `Makefile`), test layers (links `testing.md`), the golden-update process, diagnostics-are-generated, and the ADR process. |
| 11 | `docs/known-limitations.md` | **Created** | Honest deferrals (vector PDF/CMYK, GPU, WASM/untrusted extensions, animation), authoring gaps with their diagnostics, paragraph-level metrics, same-platform provenance, platform baseline, and the measured perf misses (links `performance.md`). |
| 12 | `docs/adr/README.md` | **Created (index)** | Indexes ADR-0001 and ADR-0002 with status + what each shapes. |
| 13 | `IMPLEMENTATION_LEDGER.md` | **Verified, not edited** | See "Ledger note" below. |

## Commands verified

Every command documented was run against `.venv/Scripts/arcavex.exe` from the repo root; only real
output was pasted. Verified surfaces (~40 invocations):

- `--help` for the root and all 10 top-level commands (`render`, `validate`, `doctor`, `explain`,
  `preview`, `status`, `list-runs`, `rerun`, `diff`, `batch`) and all 9 subcommand groups
  (`template`, `layout`, `style`, `effects`, `project`, `data`, `asset`, `mcp`, `ext`).
- `doctor`, `effects list`, `style list`, `mcp tools --json` (24 tools).
- `render` to png (with and without `-o`/default name), jpg (`--quality`), webp (`--lossless`), and
  pdf (ipen fa a4); `render` of the reference poster (standalone preview-data) and a
  changed-data render; `render --format story`; `render --locale fa`.
- `template inspect`, `template inspect --resolved --format a4 --locale fa`, `template new`,
  `template check`; `layout inspect`.
- `explain ARC-TPL-014`; `ext scaffold effect`, `ext validate`, `ext list`.
- Exit codes confirmed directly: success `0`, validation error `1` (undeclared locale
  `ARC-TPL-100`, unknown explain code), `validate` `0`.

All internal doc links were checked to resolve to existing files (21 primary targets, all OK).

## Inventories generated from code

- **Expression functions (9):** from the `TemplateFunction` registry
  (`src/arcavex/builtin/template_fns/core.py` → `services/template/functions.py`), cross-checked
  against `template inspect --json`.
- **Effects (15):** from `arcavex effects list` (the live registry), used verbatim in
  `template-schema.md`.
- **Diagnostics (142):** confirmed `services/diagnostics_catalog.py` has 142 entries and
  `docs/diagnostics/` has 142 `.md` files, kept in sync by `tests/unit/test_explain.py`.
- **Import-linter contracts (5):** from `[tool.importlinter]` in `pyproject.toml`.
- **Make targets (8):** from `Makefile`.

## Deliberate omissions

- **Did not gut the README's command / config / MCP tables.** The brief asked to keep the README
  tight; I collapsed the deep *authoring reference* and inline known-limitations (now fully in the
  new docs) but kept the command overview, the config/budget tables, and the MCP section in place —
  they are high-value at-a-glance content and the brief's "prefer editing in place / keep voice"
  rule argues against relocating them. Deep flag detail now lives in `cli.md`, cross-linked.
- **Did not regenerate or hand-edit `docs/diagnostics/*.md`.** They are generated from the catalog
  (`make docs-diagnostics`) and were already in sync (142 == 142); `diagnostics.md` indexes them
  rather than duplicating 142 files.
- **No screenshots/thumbnails embedded** in the README showcase. The finals are linked (repo-relative)
  rather than embedded as images, to keep the README lightweight and avoid binary-path assumptions in
  Markdown rendering; the design-review matrix already narrates each render.
- **Did not document a Python-API quick reference.** The facade (`kernel.api`) is described
  structurally in `architecture.md`, but a method-by-method API doc was out of the §12 scope and is
  not claimed.

## Ledger note (item 13 — reported, not edited)

`IMPLEMENTATION_LEDGER.md`'s `Task §12 Documentation set` row is accurate for what it lists
(CHANGELOG, `performance.md`, `testing.md`, `packaged-install.md`, benchmark harness, CI) and needs
no correction. It predates this consolidation pass, so it does not enumerate the newly added docs
(`install`, `quick-start`, `tutorials/`, `template-schema`, `cli`, `diagnostics`, `architecture`,
`contributing`, `known-limitations`, `adr/README`). Per the brief's "verify … report, don't edit"
instruction for the ledger, I left it untouched; the orchestrator may optionally extend that row to
reference the consolidated set.

## Gaps found and filled

- No consolidated **CLI reference**, **template-schema**, **architecture**, **install**,
  **quick-start**, **tutorials**, **contributing**, **known-limitations**, or **diagnostics index**
  existed — all created.
- The docs were not reachable from a single index — added the README Documentation table.
- The reference poster (the showcase) was not featured in the README — added the showcase section
  with the 10-finals table.
- No ADR index existed — added `docs/adr/README.md`.

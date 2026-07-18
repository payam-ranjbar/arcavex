# Docs brief — consolidation and gap-fill (task §12)

Most docs were written per-phase. This task is a CONSOLIDATION pass: inventory what exists,
fill the gaps, cross-link, and make the set navigable from README.md. Honesty rule: never
document capability that doesn't exist; measured numbers only from docs/performance.md.

## Required set (task §12) — audit each, create/complete as needed
1. README.md (root) — project overview, feature summary, install pointer, quick-start pointer,
   SHOWCASE the reference poster (link examples/reference-poster + a table of the 10 finals),
   docs index. Keep it tight; deep content lives in docs/.
2. docs/install.md — from-source install (uv/pip), packaged wheel install, ICU note (ADR-0001),
   doctor. Reuse docs/packaged-install.md content by LINKING, not duplicating.
3. docs/quick-start.md — 10-minute path: hello-poster render → change data → new format →
   locale → export formats (png/jpg/webp/pdf) → --resolved/--explain.
4. docs/tutorials/ — at least: (a) building a template from scratch (nodes, constraints,
   stacks, fit policies), (b) bilingual template (locales, digits, RTL, data overlays) using
   reference-poster as the worked example, (c) using + writing extensions (link extension-guide).
5. docs/template-schema.md — full authoring reference: every node kind, constraints/anchors
   (incl. logical start/end), units, styles, masks/effects params, repeat/if, expressions
   ({{ }} functions list), variables/schema.yaml, formats/patches, locales, style packs.
   Generate the diagnostics/expression-function inventories FROM the code where practical.
6. docs/cli.md — every command with synopsis + key flags + example (arcavex --help tree is
   the source of truth; verify each against the real CLI).
7. docs/diagnostics.md — the code catalog (exists? regenerate/verify against
   services/diagnostics_catalog.py), exit codes, --explain.
8. docs/extension-guide.md — exists from Phase 6; verify current, add scaffold walkthrough.
9. docs/architecture.md — microkernel map (kernel/services/builtin/clients/sdk, inward deps,
   composition root), document-state pipeline, SPI contracts table, determinism model,
   run/provenance model. Include the import-linter contract summary.
10. docs/contributing.md (or CONTRIBUTING.md) — dev setup, make targets, test layers
    (link docs/testing.md), golden update process, ADR process.
11. docs/known-limitations.md — honest list: §12 deferrals (vector PDF/CMYK, GPU, WASM,
    animation, untrusted extensions), platform baseline (win note, linux-aarch64 untested
    locally), perf misses (link performance.md), RTL isolate approach caveats.
12. docs/adr/ — index them in docs/adr/README.md.
13. Verify IMPLEMENTATION_LEDGER.md needs no doc-related row updates (report, don't edit).

## Constraints
- VERIFY every command you document by running it (.venv/Scripts/arcavex.exe ...); paste real
  output only. Do not run the full test suite; docs-only change (run nothing but the commands
  you document + ruff on nothing — no code changes at all).
- Never edit engine/source/tests. Only *.md files (and docs/ structure).
- Keep existing docs' voice; prefer editing in place over rewriting.
- Cross-link: every doc reachable from README.md docs index within 2 clicks.
- Record a coverage table (doc → status found/created/updated) in your report.

## Report
Write docs/agent-runs/docs-report.md: coverage table, gaps found, commands verified (count),
anything deliberately left out and why.

# Arcavex implementation ledger

Statuses: Not started | In progress | Implemented | Tested | Reviewed | Accepted | Deferred by specification | Externally blocked

| Spec section | Requirement | Status | Source | Tests | Acceptance | Review | Blocker |
|---|---|---|---|---|---|---|---|
| §11 Phase -1 | Skia feasibility (SkParagraph, fonts, SkSL, PNG, PDF, determinism) | Accepted | docs/adr/0001, tests (Phase 0 converts probes) | feasibility probe (9/9 pass) | probe script run 2026-07-12 | ADR recorded | — |
| §3.1 | IR: CompiledDocument/LayoutDocument, units, colors, hashing | Accepted (v0; canonical float form ticketed CR-13 for Phase 4) | src/arcavex/kernel/ir/ | tests/unit (units, colors, canonical), tests/property | hello-poster render + validate | phase-00 loop: accepted | — |
| §3.2 | Contracts (8 SPIs) | Accepted (v0 contracts; Effect/Mask/Shape/AssetDecoder impls in later phases) | src/arcavex/kernel/contracts/ | tests/unit/test_registry.py | — | phase-00 loop: accepted | — |
| §3.3 | Registry + bootstrap + extension loader | Accepted (registry+bootstrap; local ext loader = Phase 6) | src/arcavex/kernel/registry/, bootstrap.py | tests/unit/test_registry.py | lint-imports | phase-00 loop: accepted | — |
| §3.4 | Pipeline orchestrator | Accepted (v0 compile→layout→render→export sequencing in facade) | src/arcavex/kernel/api.py | tests/e2e/test_cli.py | render CLI | phase-00 loop: accepted | — |
| §3.5 | Observer-only hooks | Not started | | | | | |
| §3.6 | Diagnostics model + codes + explain | Accepted (model+codes+located+hints; explain = Phase 1) | src/arcavex/kernel/diagnostics.py | tests across suites | validate --json failure paths (exit 1/3/4/5 demonstrated) | phase-00 loop: accepted | — |
| §3.7 | Service API facade | Accepted (render_file, validate_template; rest per later phases) | src/arcavex/kernel/api.py | tests/e2e | CLI acceptance | phase-00 loop: accepted | — |
| §4.1 | Template system: loader, expressions, styles, formats/locales/patches, compiler | Accepted through Phase 1 scope (split files, repeat/if, functions, variable schema; styles Phase 3, format/locale patches Phase 2) | src/arcavex/services/template/ | tests/unit (expressions, structural, split, variables, functions) | template new/check/inspect/split, validate | phase-01 loop: accepted | — |
| §6.1.3+§3.7 | doctor, explain, template authoring commands, watch preview | Accepted | src/arcavex/services/{doctor,explain,authoring}.py, clients/watch.py | tests/unit + tests/e2e | doctor --json, explain, preview --watch session | phase-01 loop: accepted | — |
| §4.2 | Anchor layout solver + fit policies | Not started | | | | | |
| §4.3 | Text stack (SkParagraph, bundled fonts, BiDi/RTL, locale digits) | Not started | | | | | |
| §4.4 | Effect system + built-in effects | Not started | | | | | |
| §4.5 | Skia renderer backend, masks, surface pool | Not started | | | | | |
| §4.6 | Exporters: PNG/JPEG/WebP/PDF | Not started | | | | | |
| §4.7 | Asset system: CAS, sidecars, decode guards, derived cache | Not started | | | | | |
| §5 | Projects, library, provenance, runs, rerun, diff, versioning | Not started | | | | | |
| §6.1 | CLI (direct + project modes, JSON, exit codes) | Not started | | | | | |
| §6.2 | MCP server | Not started | | | | | |
| §6.3 | DX contract (watch preview, inference rules, naming) | Not started | | | | | |
| §7 | Trusted local extension SDK + workflow | Not started | | | | | |
| §8.3 | Local safety and resource limits | Not started | | | | | |
| §8.5 | Testing strategy (property, snapshots, golden, e2e, CLI, MCP sessions) | Not started | | | | | |
| §12/spec | Deferred: hostile-extension isolation, WASM, GPU, vector PDF/CMYK, animation, hosted concerns | Deferred by specification | — | — | — | — | — |
| Task §9 | Reference poster bilingual template + 5 formats × 2 locales | Not started | | | | | |
| Task §12 | Documentation set | Not started | | | | | |

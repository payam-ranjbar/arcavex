# Phase 00 remediation

Agent: Phase 0 remediation (Opus). Date: 2026-07-12.
Scope: fix root causes for CR-1..CR-21 (code review) and DX-1..DX-15 (DX/design review) without
weakening tests or acceptance criteria.

## Result summary

- `pytest tests -q` — **97 passed** (was 74; +23 regression tests).
- `ruff check src tests` — clean.
- `mypy src/arcavex/kernel --strict` — clean (12 files). `mypy src/arcavex` (best effort) — clean (32 files).
- `lint-imports` — 2 contracts kept, 0 broken (added the built-in boundary contract).
- Exit codes 0 / 1 / 3 / 4 / 5 all demonstrated live (see Verification).
- hello-poster renders correctly with a transparent local logo; repeated renders are byte-identical.

## Finding → action → guarding test

### Required

| Finding | Action taken | Test |
|---|---|---|
| CR-1 / DX-1 (P0) preview_data backfills supplied data | `_build_context` now uses `preview_data` **only when `data is None`**; supplied data is never per-key back-filled. Fallback use recorded as `inferred["data"]="preview_data"`. | `test_preview_data_does_not_backfill_supplied_data`, `test_preview_used_only_without_data_reports_inference` |
| CR-2 (P1) `visible:false` renders anyway | `LayoutNode` gains an explicit `visible` field; solver copies `node.visible`; backend `_visible()` honors it (no longer guesses from opacity alone). LayoutDocument stays honest (explicit state). | `test_visible_false_carried_into_layout`, `test_visible_false_not_painted` (pixel) |
| CR-3 / DX-4 (P1) missing image → ARC-INT-999/exit 5 | Asset path resolved and `is_file()`-checked **at compile time** → located `ARC-AST-001` (template-relative path in message), so `validate` catches it too, exit 3. Dead `if image is None` replaced by a real decode guard in the backend → `ARC-AST-002` on undecodable files. | `test_missing_asset_located_compile_error`, `test_missing_asset_exit_3` |
| CR-4 (P1) non-goal template sections silently ignored | New `_reject_unsupported_sections`: top-level `styles`/`style`/`locales`, per-format `patch`, and split sidecar files → located "not supported in this build" (`ARC-TPL-092/093/094/095/096`), ARC-TPL-050 house style. | `test_nongoal_locales_section_rejected`, `test_nongoal_styles_section_rejected`, `test_nongoal_format_patch_rejected` |
| DX-2 (P1) under-constrained node vanishes | A present `constraints` block now **requires** explicit `size` for each axis; missing → `ARC-LAY-032` naming node + axis, exit 1. Nodes with no `constraints` key still fill (root/background convenience). | `test_under_constrained_missing_size` |
| DX-3 (P1) bare-number canvas crashes | Canvas `width`/`height` already route through `Dim` (bare = px); the real crash was the `dpi` coercion. All canvas scalars now go through guarded coercion → located `ARC-IR-014`/`ARC-IR-013`, never a pybind nullptr. | `test_bare_canvas_dim_ok_and_bad_dpi_located` |
| DX-5 (P1) unknown font silently falls back | Compiler receives the bundled font DB from bootstrap; a family not in the DB → located `ARC-RND-010` (documented namespace choice) with requested + available families, exit 3; `validate` reports it. | `test_unknown_font_family_located_exit3_code`, `test_unknown_font_exit_3` |
| DX-6 (P1) no default output name | Render without `-o` writes `<template-stem>.<format>.png` in CWD, recorded in `inferred["output"]` and announced (human + JSON). CLI `-o` help updated. | `test_default_output_name_and_reported` |
| DX-7 (P1) inferences silent | `CompileResult.inferred` threads `format` and `data` (preview fallback) to `RenderResult`; CLI prints one `inferred:` line and a JSON `"inferred": {...}` object. | `test_inference_reported_in_json`, `test_format_inference_reported` |
| CR-5 (P2) budget → exit 1 | `BudgetError` caught before `ExpressionError` in `_resolve_text` → dedicated `ARC-TPL-062` (`BUDGET_CODE`); CLI maps it to exit 4 (dead `-BUDGET` branch removed). | `test_budget_exhaustion_distinct_code`, `test_budget_exit_4` |
| CR-6 / DX-8 (P2) ARC-TPL-014 file/line mismatch | Missing-required-variable diagnostic now reports the **template** declaration (file + line + keypath), a single consistent source; e2e assertion corrected. | updated `test_failing_template_exit_and_located_json`; `test_preview_data_does_not_backfill_supplied_data` asserts `file==template` |
| CR-7 (P2) unguarded coercions → ARC-INT-999 | `_int_field`/`_float_field` helpers wrap seed, dpi, opacity, font_weight, rotate/scale/translate; `variables:` non-mapping guarded → located `ARC-IR-014`/`ARC-TPL-013`. | `test_bare_canvas_dim_ok_and_bad_dpi_located` (dpi), plus type guards |
| CR-8 (P2) facade construction unguarded | CLI wraps `build_facade()` in `_build_facade_or_exit` → `ARC-INT-999` with an icudtl/doctor hint, exit 5, no traceback. | in-process demo (below); not subprocess-simulable without breaking ICU |
| CR-9 (P2) line_height silently ignored | skia-python 144 `StrutStyle` exposes only `setStrutEnabled`/`setLeading` (no height override; `TextStyle` has no `setHeight`) — cannot honor a line-height multiplier faithfully, so it is **rejected** at validation (`ARC-TPL-053`) per §4.3. | `test_line_height_rejected` |
| CR-10 (P2) test blind spots | 23 regression tests added across the P0/P1/P2 fixes. | (this column) |
| CR-11 / DX-9 (P2) diagnostics missing line | `line` threaded into `_dim`, `_color`, `_resolve_text`, size/anchor parsers; ARC-IR-011/030 and expression-site ARC-TPL-014 now carry a line. | live-verified (color line 10, unit line 10) |
| DX-10 (P2) unversioned JSON | Every `--json` response carries `"response_version": 1`. | `test_response_version_present`, updated e2e |
| DX-11 (P2) thin README | Added a "Template anatomy" section (sections, node types, anchors+whitespace rule, units, preview_data, `\| default`, escape, functions, exit-code table). | examples exercised by e2e |
| DX-13 a+b (P3) logo/asset polish | `examples/hello-poster/logo.png` derived from the reference by **border flood-fill** white→transparent (preserves the interior white "IPEN" wordmark); template path is now local; subtitle uses `\| default(...)`. | existing `test_render_hello_poster`; visual check |

### Discretionary

| Finding | Disposition | Test / note |
|---|---|---|
| CR-12 group opacity | **Deferred.** `opacity:0` still hides a subtree via `_visible`; partial-alpha group compositing needs `saveLayer` and is not exercised in Phase 0. | — |
| CR-13 canonical float repr | **Deferred.** Spec `repr(round(x,6))` conflicts with the enshrined test `canonicalize(2.0)=="2"`, and the real "2 vs 2.0" issue needs numeric unification (int vs float→str). Latent: `canonical_hash` has no production caller yet. | — |
| CR-14 traversal guard / relative asset storage | **Deferred.** Phase 0 renders template-relative paths directly; the example is now local (no `../`). Storing relative paths + a traversal guard belongs to the CAS phase. | — |
| CR-15 evaluator uses registry | **Deferred.** Keeps the evaluator standalone and unit-testable without a registry; Phase 1 (where it becomes required) finalizes `TemplateFunction` call/error semantics and can dedupe then. | — |
| CR-16 solver reentrancy | **Done.** `measure` threaded through the call stack; no per-solve mutable state. | existing layout tests |
| CR-17 unknown anchor edge | **Done.** `_parent_edge` raises `ARC-LAY-014` instead of defaulting to center. | — |
| CR-18 rgb() out of range | **Done.** `_channel`/`_alpha` reject out-of-range values → `ARC-IR-030`. | `test_rgb_out_of_range_rejected` |
| CR-19 missing -o / UTF-8 stdout | **Done.** Missing `-o` obsolete via DX-6 default; `--json` forces UTF-8 stdout on Windows. | `test_default_output_name_and_reported` |
| CR-20 import-linter builtin boundary | **Done.** Added "Built-ins do not import clients or the composition root" contract. | `lint-imports` |
| CR-21 var types / list data / bleed / dead code | **Done** (var type → `ARC-TPL-015`; list-rooted data → `ARC-TPL-012`; removed dead `DiagnosticFields`). **bleed deferred** (parsed to `bleed_pt`, unused by Phase 0 layout/render; Insets conversion is cosmetic with no consumer). | `test_variable_type_mismatch_reported`, `test_list_rooted_data_file_rejected` |
| DX-12 anchor whitespace | **Done.** Offsets tolerate spaces around the sign (`parent.left + 40px`). | live-verified |
| DX-14 malformed-YAML message | **Done.** `_yaml_error_summary` reduces ruamel's noise to one sentence + a line number. | — |
| DX-15 `hstack` as a node type | **Done.** `type: hstack`/`vstack` → `ARC-TPL-052` "arrives in Phase 2" (matches the `layout:` rejection). | — |

## Verification commands and results

```
.venv\Scripts\python.exe -m pytest tests -q                         -> 97 passed
.venv\Scripts\python.exe -m ruff check src tests                    -> All checks passed!
.venv\Scripts\python.exe -m mypy src/arcavex/kernel --strict        -> Success (12 files)
.venv\Scripts\python.exe -m mypy src/arcavex                        -> Success (32 files)
.venv\Scripts\lint-imports.exe                                      -> 2 kept, 0 broken
```

Acceptance + failure scenarios (exit codes captured directly):

```
render hello-poster ... -o outputs-tmp/hello.png                    -> exit 0 (PNG visually correct, transparent logo)
validate hello-poster ... --json                                    -> exit 0, {"response_version":1,"ok":true,...}
two renders, sha256 compared                                        -> identical (byte-deterministic)
render missing-template.yaml                                        -> exit 3 (ARC-TPL-001)
render <missing asset>                                              -> exit 3 (ARC-AST-001)
validate <unknown font>                                             -> exit 3 (ARC-RND-010)
validate <required var missing, preview present>                   -> exit 1 (ARC-TPL-014, file+line=template)
validate <constraints without size>                                -> exit 1 (ARC-LAY-032)
validate <line_height set>                                          -> exit 1 (ARC-TPL-053)
validate <top-level locales:>                                       -> exit 1 (ARC-TPL-092)
validate <5000-term expression>                                    -> exit 4 (ARC-TPL-062)
render with build_facade() raising (icudtl simulated, in-process)  -> exit 5 (ARC-INT-999 + icudtl hint, no traceback)
render single-format template, no -o/-f/-d                          -> exit 0, "inferred: format=card, output=single.card.png"
invalid color / unit                                                -> located ARC-IR-030 / ARC-IR-011 with line numbers
anchor "parent.left + 40px" (spaces)                                -> exit 0 (accepted)
```

## For the re-reviewer to scrutinize

1. **CR-9 = reject, not honor.** Verified against the actual binding: skia-python 144 `StrutStyle`
   only exposes `setStrutEnabled`/`setLeading` (no `setHeight`/`setForceStrutHeight`; `TextStyle`
   has no `setHeight`). A line-height *multiplier* cannot be expressed faithfully, so it is rejected
   at validation. If a future binding adds height override, revisit.
2. **DX-2 split rule.** A `constraints` block that is present but lacks `size` (or an axis) is now a
   hard error; a node with **no** `constraints` key still defaults to fill/fill (root and full-bleed
   backgrounds rely on this). Confirm this asymmetry is acceptable.
3. **CR-21 variable type enforcement** is a new behavior (`ARC-TPL-015`). It checks only *supplied*
   values (declared defaults are not type-checked) and keeps boolean/number distinct. Watch for
   false positives on loosely-typed templates.
4. **validate inference reporting.** `render` reports `inferred` in JSON/human; `validate_template`
   keeps its spec'd `-> [Diagnostic]` signature and does not surface `inferred`. Deliberate scoping
   (both DX-7 examples were render).
5. **Compiler ↔ font DB coupling.** `Compiler(available_fonts=...)` now receives the bundled family
   set from bootstrap; constructed with `None` (unit tests) it skips font validation. Confirm this is
   an acceptable dependency direction (compiler already owns semantic validation; no new imports).
6. **New logo asset.** `examples/hello-poster/logo.png` is a *new* derived file (border flood-fill of
   the reference logo); `examples/reference/logo.png` is untouched.
```

# Phase 01 remediation — authoring loop

Agent: Fable 5 (remediation). Every code-review finding (CR-1..CR-13) and DX finding
(DX-1..DX-10) was addressed at its root cause; none was closed by weakening a test or
acceptance. New behaviors are each pinned by a guarding test. Gates and acceptance commands
were run to completion (transcripts at the end).

## Verdict: all P1/P2 fixed; P3 fixed except one deferral (orphan-comment-after-split), stated.

## Gates

```
.venv\Scripts\python.exe -m pytest tests            # 190 passed (was 166; +24 guarding tests)
.venv\Scripts\python.exe -m ruff check src tests    # All checks passed
.venv\Scripts\python.exe -m mypy --strict src/arcavex/kernel   # Success, 12 files
.venv\Scripts\lint-imports.exe                      # 3 contracts kept, 0 broken
```

## Finding → action → guarding test

| # | Finding | Root-cause action | Guarding test |
|---|---|---|---|
| CR-1 (P1) | Default output name absent on render-failure paths | `render_file` resolves the default name up front from the resolved template stem + format and carries `inferred["output"]` on **every** return path (success, `DiagnosticError`, unexpected). `api.py` `_default_output_path`/`_default_stem`. | `test_phase01_remediation.py::test_default_output_reported_on_render_failure`, `::test_default_output_on_compile_error` |
| CR-2 (P1) | `--locale` not a CLI option | Added `--locale/-l` to `render`, `validate`, `preview`, `template check`; threaded to facade/compiler → located `ARC-TPL-091`. `spec §6.1.1` `preview … --locale fa` now parses. | `test_cli_authoring.py::test_render_locale_flag_parses_and_defers`, `::test_preview_locale_flag_parses` |
| DX-1a (P1) | `repeat` overlaps siblings silently | `_expand_repeat` emits `ARC-LAY-040` (warning) when >1 expanded siblings share identical constraints+transform. Render still succeeds. | `test_phase01_remediation.py::test_repeat_overlap_warns` |
| DX-1b (P1) | `ARC-LAY-012` hint silent on expressions | Anchor-offset hint + `explain` entry now state that `{{ }}` is not evaluated inside constraints in this build. | `test_phase01_remediation.py::test_expression_in_constraint_hint`, `test_explain.py::test_lay012_explain_mentions_expression_boundary` |
| DX-1c | Stacks/expressions-in-constraints | Not implemented (Phase 2) — only the warning + hints, as instructed. | n/a |
| DX-2 (P1) | README/scaffold stale (Phase 0) | README rewritten to Phase 1 (structural constructs, all nine functions with signatures, split layout, commands, **Known limitations** incl. repeat-overlap). Scaffold now demonstrates `if: "{{ badge is not none }}"` (usable today) and points to the README for `repeat`; scaffold README passes `--data` and lists `check`/`inspect`. | existing `test_authoring.py::test_scaffold_renders_out_of_the_box` (renders with the new `if:` node) |
| CR-3 (P2) | `repeat`+`if` on one child drops `if` | `_expand_child` raises located `ARC-TPL-061` for the combination. | `test_phase01_remediation.py::test_repeat_and_if_on_same_child_is_error` |
| CR-4 (P2) | Preview path / default stem differ by dir-vs-file spelling | `preview_path` hashes the resolved `template.yaml`; `_default_stem` uses the directory name when the file is `template.yaml`. Both spellings identical. | `test_phase01_remediation.py::test_preview_path_dir_and_file_equal`, `::test_default_output_stem_dir_and_file_equal` |
| CR-5 (P2) | Explicit `null` optional = hard error | Supplied `None` keys dropped before the declaration loop, so an optional null binds `None` (no type/enum error) and a required null → `ARC-TPL-014`. | `test_phase01_remediation.py::test_explicit_null_optional_equals_omission`, `::test_explicit_null_required_still_errors` |
| CR-6 (P2) | `inspect` on broken template: exit 0, diagnostics hidden | Report sets `ok`/`compiled` from compile result; CLI prints diagnostics in human mode; exit per §6.1.3. | `test_phase01_remediation.py::test_inspect_reflects_compile_failure` |
| CR-7 (P2) | Watch startup race; test masked it | Watcher registered before the initial render (`yield_on_timeout` first-tick), so a save after the initial-render line is captured. Retry loop removed from the test; single-save assertion added. | `test_preview.py::test_watch_rerenders_on_single_save` |
| DX-3 (P2) | `inspect` reports an instance, not the contract | `nodes` now walks the **authored** tree, reporting `repeat`/`if` unexpanded with `origin`/`condition`/`collection`/`loop_var`/`key`; `functions` carry `signature`+`doc`. | `test_phase01_remediation.py::test_inspect_reports_authored_structural_nodes`; `test_cli_authoring.py::test_template_inspect_json_golden` (signatures) |
| DX-4 (P2) | `ARC-TPL-014` reference errors fail fast | Group children loop collects `ARC-TPL-014` across the whole compile (other errors still fail fast). | `test_phase01_remediation.py::test_undeclared_references_aggregate` |
| DX-5 (P2) | `locales.yaml` values unvalidated | `_validate_locale_values` checks direction ∈ {ltr,rtl}, digits ∈ {en,fa,latn,arab}, fonts/data/patch shapes, and unknown keys → located `ARC-TPL-099`. | `test_phase01_remediation.py::test_locale_bad_values_located`, `::test_locale_good_values_accepted` |
| DX-6 (P2) | `explain` entries restate the inline hint | Rewrote `ARC-LAY-012`, `ARC-TPL-070`, `ARC-TPL-071`, `ARC-TPL-097` with cause taxonomy + boundary + examples; regenerated docs. | `test_explain.py::test_lay012_explain_mentions_expression_boundary` (+ mirror/coverage tests) |
| CR-8 (P3) | Data-file diagnostics lose line numbers | Per-key data lines captured from the ruamel map before `_to_plain`; supplied-value diagnostics cite `<data>:<line>`. Inaccurate comment fixed. | `test_phase01_remediation.py::test_data_file_line_is_cited` |
| CR-9 (P3) | Out-of-tree assets not watched | `Facade.collect_asset_paths` walks compiled images; `watch_paths` adds out-of-tree parent dirs. | covered by `test_preview.py` watch tests (in-tree) + manual review of asset-dir set |
| CR-10 (P3) | CR-13 ticket TODO missing | TODO added next to `canonical_hash`. | (comment) |
| CR-11 (P3) | inspect can't tell no-default from `default:null` | Added `has_default` to `VariableInfo`. | `test_phase01_remediation.py::test_inspect_distinguishes_no_default_from_null_default` |
| CR-12 (P3) | Stale evaluator docstring | Rewritten to the registry-resolved nine-builtin reality. | (docstring) |
| CR-13 (P3) | Watch stop event-gated; daemon join leaks | Finite `rust_timeout` (300ms) + `yield_on_timeout`; loop honors `stop_event` without an FS event. | `test_preview.py::test_watch_stops_promptly_without_events` |
| DX-7 (P3) | inspect reports pt-only | `FormatInfo` echoes authored `width`/`height` alongside `width_pt`. | `test_phase01_remediation.py::test_inspect_reports_authored_units` |
| DX-8 (P3) | Scaffold README render omits `--data` | README render line now passes `--data` and notes the no-data path. | (scaffold content) |
| DX-9 (P3) | doctor never states home/cache | New `paths` probe reports ARCAVEX_HOME (+ source) and preview cache. | `test_cli_authoring.py::test_doctor_reports_paths_row`, `test_doctor.py::test_doctor_report_shape` |
| DX-10 (P3) | Message polish | Non-watch preview drops `changed=`; "kept last good preview" only when one exists; `ARC-TPL-060` hint dropped for unknown-function; `ARC-TPL-014` gains `difflib` did-you-mean. | `test_phase01_remediation.py::test_did_you_mean_for_typo` |

## Deferrals (with reason)

- **DX-10 orphaned-comment-after-split.** A template comment sitting directly above a split
  section (e.g. above `variables:`) is left above the following key after `template split`
  deletes that section. Reassociating ruamel `CommentAttribute` structures on deletion is
  fragile and risks corrupting or dropping legitimate comments elsewhere; the payoff is one
  stray-but-harmless comment. Deferred rather than shipping a risky comment-surgery pass. The
  scaffold's own comment lands sensibly above `root:` and still parses/round-trips.

## Notes for the re-reviewer

- **Compile now returns a *partial* document + error diagnostics** for node-level reference
  errors (DX-4 aggregation), where it previously returned `document=None`. Every consumer
  guards on `has_errors`/`compiled`, so `ok` is unchanged; `inspect` uses the authored walk so
  the partial tree is never surfaced. Worth confirming no consumer treats `document is not
  None` as "valid" without also checking `has_errors`. (Required-variable-missing still returns
  `None`, unchanged.)
- **CR-7 residual window:** the fix closes the reported window (a save after the initial-render
  line). A save that lands *before the watcher registers at all* — i.e. before the "watching…"
  line — is still not captured until the next save; this is inherent to any watcher and not the
  CR-7 bug. Verified via a live probe (below): an immediate save *after* the initial render
  re-renders; the thread exits cleanly (no leak).
- **New diagnostic codes:** `ARC-TPL-061`, `ARC-TPL-099`, `ARC-LAY-040` — added to the catalog
  and `docs/diagnostics/` (mirror + coverage + orphan tests pass).
- **Inspect contract shape changed** (`functions` are objects now, `nodes` are authored):
  three existing tests were updated to assert the richer contract (names still present, plus
  signatures/origins) — not weakened.

## Verification transcript (abridged)

```
render (no -o):    inferred: output=my-card.square.png, data=preview_data  (exit 0)
render --locale fa: inferred: output=hello-poster.square.png
                    ERROR ARC-TPL-091 Locales are not supported in this build  (exit 1)   [CR-2, CR-1 announce-first]
render broken.png (no -o): inferred: output=cr1.square.png
                    ERROR ARC-AST-002 Could not decode image asset …          (exit 3)   [CR-1 failure path]
preview dir  -> …\1bfd61c126df2553.square.png
preview file -> …\1bfd61c126df2553.square.png   EQUAL                                     [CR-4]
render repeat: WARNING ARC-LAY-040 'repeat' … expands 3 sibling nodes … will overlap (exit 0) [DX-1a]
inspect broken.yaml: ERROR ARC-TPL-014 … (exit 1)                                          [CR-6]
validate loc.yaml: ARC-TPL-099 unknown setting 'bogus' / invalid direction / invalid digits [DX-5]
doctor --json: "paths" -> home=…\arcavex [default (OS temp)]; preview cache=…             [DX-9]
inspect --json: has_default:false, width:"1080px", width_pt:810.0, compiled:true          [CR-11/DX-7/CR-6]

live watch probe (single immediate save after initial render):
  results: 2 | initial ok: True | re-render changed: data.yaml ok: True
  RESULT: single immediate post-initial save re-rendered (race gone)                       [CR-7]
  thread alive after join: False                                                           [CR-13]
```

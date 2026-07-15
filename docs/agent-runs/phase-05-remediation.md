# Phase 05 remediation — MCP authoring surface

**Agent:** Phase 5 remediation (Opus). **Base:** phase-05 review commits (code review `eb50d77`;
DX review same). **Scope:** the P0/P1/P2 findings in `phase-05-code-review.md` (CR-1..CR-6) and
`phase-05-dx-design-review.md` (DX-1..DX-7). Root-cause fixes only; no test or acceptance was
weakened.

## Finding → action → test

| # | Sev | Finding | Root-cause action | Proof |
|---|-----|---------|-------------------|-------|
| DX-1 | P0 | `data=`/`template=` passed to the facade as raw strings (`# type: ignore`), crashing `template_validate`/`render`/`render_preview`/`layout_inspect` with `ARC-INT-999` (`'str' has no attribute 'with_suffix'`) on any external data file | `mcp_server.py`: every path-like arg (`template`, `data`, `output`, `root`, `project`, `path`) coerced via `Path(...)` / `_opt_path(...)` at the boundary; all `# type: ignore[arg-type]` removed | `test_external_data_file_through_all_four_tools`, `test_external_data_file_through_real_server_dispatch`; DX repro `loop14`/`loop16` now `ok: True` |
| DX-2 | P0/P1 | No MCP tool could render a project or originate a recorded run, yet `run_list`/`_diff`/`_rerun` were exposed | Added `arcavex_project_render` (→ `render_project`) and `arcavex_render_record` (→ `record_render`) tools | `test_project_render_creates_a_recorded_run_reachable_from_run_list`, `test_render_record_produces_a_recorded_run` |
| DX-3 | P1 | `template_inspect` never reported locales (§4.1.1 promises it) — the shared `TemplateInspectReport` had no field | Added `LocaleInfo` model + `locales` field to `TemplateInspectReport`; `AuthoringService.inspect` populates it (name/direction/digits/has_fonts/has_patch); CLI human output prints locales | `test_inspect_reports_locales` (en/fa on ipen-bilingual) |
| DX-4 | P1 | `template_patch` did no leaf-field check — `fontsize` (vs `font_size`) returned `ok/applied:1` and wrote a bogus key | `patch_template` now field-checks each `set` leaf against the compiler's own whitelists (`_STYLE_KEYS`/`_FIT_KEYS`/`_PARAGRAPH_KEYS`/`_CONSTRAINT_KEYS`/`_SIZE_MAP_KEYS`) → located `ARC-TPL-051` before any write; valid edits still apply | `test_patch_typo_leaf_field_is_rejected_without_writing`, `test_patch_valid_leaf_field_still_applies` |
| CR-1 | P2 | `PatchOp` with 0 or ≥2 verbs silently applied one and dropped the rest | Boundary check rejects any op not naming exactly one verb → located `ARC-TPL-092`, nothing written | `test_patch_zero_or_multi_verb_ops_are_rejected` (parametrized) |
| CR-2 | P2 | `patch_template`/`set_data`/`import_data`/`add_asset`/`annotate_asset` were MCP-only (no CLI) | Added thin CLI subcommands `template patch`, `data set`, `data import`, `asset add`, `asset annotate` (parse+present only); README synced | `tests/e2e/test_phase05_cli_remediation.py` (5 tests) |
| DX-5 | P2 | No MCP tool to discover styles/effects | Added `arcavex_style_list`, `arcavex_style_inspect`, `arcavex_effects_list` (→ `list_styles`/`inspect_style`/`list_effects`) | `test_style_and_effect_catalog_tools` |
| DX-6 | P2 | `data_set`/`import_data` didn't validate keypaths — a typo (`titel`) was a silent permanent no-op | New `ARC-TPL-112` **warning** when a top-level data key matches no declared template variable (both tools); `ok` stays true (extra data can be legitimate) | `test_data_set_typo_keypath_warns`, `test_data_set_valid_keypath_is_clean`, `test_data_import_typo_keypath_warns` |
| CR-3 | P3 | Client parse-present boundary was review-only | New import-linter contract: `clients.cli` + `clients.mcp_server` may not import `services`/`builtin` (`allow_indirect_imports`, so the shared `watch` helper is governed separately) | `lint-imports` → 4 contracts kept |
| CR-4 | P3 | README had zero MCP mentions | Added an "MCP authoring surface" section (serve/tools, 24-tool catalog, the inspect→patch→validate→preview→render loop) + the 5 new CLI rows | README |
| CR-5 | P3 | `set_data`/`import_data` validation is compile-only (no layout) | Documented honestly in the `DataReport` docstring and `docs/backlog.md` (a data edit's geometric effect needs `layout_inspect`/`render_preview`) | docstring + backlog |
| CR-6 | P3 | Preview timings non-reproducible | Left intentionally: faithfully mirrors the CLI `PreviewResult` (durations, not timestamps); no output bytes affected | — |

New diagnostic code: **`ARC-TPL-112`** (registered in the catalog + `docs/diagnostics/ARC-TPL-112.md`,
covered by the existing emitted-code/docs-mirror tests). Reused existing `ARC-TPL-051` (unknown
field) and `ARC-TPL-092` (invalid patch op).

MCP tool catalog grew 19 → **24** (`arcavex mcp tools --json`, `response_version: 1`). The
schema-parity test (`test_output_schemas_match_facade_models`) and the delegates-to-facade test
were extended to the five new tools, so parity remains asserted byte-for-byte.

## Verification transcript (final)

```
.venv/Scripts/python.exe -m pytest tests -q                    # 479 passed (was 461 + new regressions)
.venv/Scripts/python.exe -m ruff check src tests               # All checks passed!
.venv/Scripts/python.exe -m mypy --strict src/arcavex/kernel   # Success: no issues (12 files)
.venv/Scripts/lint-imports.exe                                 # Contracts: 4 kept, 0 broken
.venv/Scripts/arcavex.exe mcp tools --json                     # 24 tools, response_version 1
```

### External-data-file proof (the DX-1 blind spot)

`loop14_isolate_bug.py` — the reviewer's isolation matrix, through the real tool wrapper — now:

```
=== A: render(data=<str>, locale='en') ===          ok: True []
=== B: render(data=<str>, locale=None) ===          ok: True []
=== C: render(data=None, locale='en') ===           ok: True []
=== D: template_validate(data=<str>, locale='en') === ok: True []
=== E: layout_inspect(data=<str>, locale='en') ===  ok: True []
=== F: render_preview(data=<str>, locale='en') ===  ok: True []
```

`loop16_server_dispatch_databug.py` — through the real `FastMCP` `server.call_tool` dispatch (an
actual MCP client over stdio):

```
([TextContent(text='{ "response_version": 1, "ok": true, "diagnostics": [] }')],
 {'response_version': 1, 'ok': True, 'diagnostics': []})
```

Both previously returned `ARC-INT-999` with `AttributeError("'str' object has no attribute
'with_suffix'")`. The create-and-correct exit scenario (`tests/mcp_sessions/test_create_and_correct.py`)
still passes.

## Files touched

- `src/arcavex/clients/mcp_server.py` — Path coercion (DX-1), 5 new tools (DX-2/DX-5), instructions.
- `src/arcavex/clients/cli.py` — 5 new authoring subcommands (CR-2), locales in inspect output (DX-3).
- `src/arcavex/kernel/api.py` — `LocaleInfo` + `locales` field (DX-3); `DataReport` docstring (CR-5).
- `src/arcavex/services/authoring.py` — locale projection (DX-3); patch verb-count + leaf-field
  validation reusing the compiler whitelists (CR-1/DX-4).
- `src/arcavex/services/orchestrator.py` — keypath-vs-declared-variable warnings (DX-6).
- `src/arcavex/services/diagnostics_catalog.py` + `docs/diagnostics/ARC-TPL-112.md` — new code.
- `pyproject.toml` — client import-boundary contract (CR-3).
- `README.md`, `docs/backlog.md` — MCP surface + CLI parity (CR-4), compile-only note (CR-5).
- Tests: `tests/mcp_sessions/test_phase05_mcp_remediation.py`,
  `tests/e2e/test_phase05_cli_remediation.py`, updated `tests/mcp_sessions/test_schema_parity.py`.

## Where to scrutinize

- **DX-4 leaf check is deliberately targeted, not a full re-compile.** It validates only the
  `set` leaf of fixed-vocabulary blocks (style/fit/paragraph/constraints[/size]) so a pre-existing
  unrelated error elsewhere never blocks a legitimate patch (the create-and-correct loop patches a
  broken template). Node-level fields and anchor edges have an open/contextual vocabulary and are
  left to the compiler's full validate — so a bogus *node-level* key still isn't caught by patch
  (by design; the next `validate` catches it). The check reuses the compiler's own frozensets, so
  it cannot diverge from what `validate` accepts.
- **DX-6 is a warning, not an error**, and only fires when the template declares variables (a
  variable-less template or an unreadable template suppresses it) — chosen so intentionally-extra
  data stays legal while a typo still gets a signal.
- **CR-3 uses `allow_indirect_imports`** so the contract governs each client module's *own*
  imports; `clients.watch` legitimately imports `services.template.loader` and is out of scope of
  this contract (it is not one of the two parse-present clients the brief named).

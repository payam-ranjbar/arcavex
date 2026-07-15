# Phase 04 remediation — projects & provenance

**Agent:** Phase 4 remediation (Opus). **Base:** Phase 4 (`599e249`), Windows / `.venv`.
**Verdict:** all required + P2 items fixed at root cause; discretionary P3s done. Gates green,
determinism re-verified.

## Finding → action → test

| Finding | Root-cause action | Test(s) |
|---|---|---|
| **CR-1 / DX-2** patch not a hashed manifest input; diff can't attribute it | `RunManifest.patch: InputRef` — the applied project override is canonically hashed (`_patch_input_ref`) and threaded through `_execute_run`/`rerun` → `_finalize`; also folded into the run-id fingerprint. `_diff_metadata` compares `overrides` + `overrides.hash`. | `test_patch_is_a_hashed_manifest_input`, `test_no_patch_leaves_manifest_patch_null`, `test_diff_attributes_a_patch_only_change` |
| **DX-3 / CR-3** rerun byte-identity silently contingent on live override; can't say why it broke | `rerun` recomputes input hashes into a fresh manifest and `_detect_drift` diffs them against the recorded one; drift is named in `RerunReport.drift`, `reproduction.json` `input_drift`, the CLI (`changed on disk: …`), and a new `ARC-RUN-002` warning. | `test_rerun_names_patch_drift`; CLI transcript |
| **CR-2** diff omits asset changes | `_diff_metadata` compares per-path `sha256`, emitting `asset[<path>]` for each add/remove/change. | `test_diff_attributes_an_asset_change` |
| **DX-1** `validate`/`preview` have no project mode | `Orchestrator.project_inputs` resolves a project's compile inputs; facade `validate_project`/`preview_project` compile+layout / render each format×locale; CLI `validate`/`preview` take an optional `TEMPLATE` and discover the project, no-project → `ARC-PRJ-001` (not a Typer usage error). | `test_validate_project_mode`, `test_validate_project_mode_surfaces_broken_data`, `test_validate_bare_no_project_is_helpful`, `test_preview_project_mode` |
| **DX-4** `project upgrade` never renders/diffs (spec §5.5 steps missing) | `_upgrade_previews` renders old + target over current data and reports dssim per output; when the override is stale on the target it retries without it (`patch_applied=False`) so a preview is still produced. `_node_structural_diff` adds `added_nodes`/`removed_nodes`. | `test_upgrade_reports_node_path_and_structural_diff`, `test_upgrade_previews_when_patch_still_applies`; CLI transcript |
| **DX-5** stale-patch report gives an array index, not the node path | `_stale_patch_paths` checks every op against the target's authored node ids and returns `UpgradeStalePath{op, path, node_id, detail}`; `stale_paths` now holds node paths. | `test_upgrade_reports_node_path_and_structural_diff` |
| **DX-6** README never documents project overrides | Added a "Project overrides" subsection (dir, `<template>.patch.yaml` name, op syntax, PROJECT resolution layer, provenance). | README |
| **DX-7** `list-runs` can't see direct-mode runs | `list_runs(..., path)` + `--path` option; falls back to `./outputs` when no project is discoverable; a single run dir is also accepted. | `test_list_runs_direct_mode_by_path` |
| **DX-8** §6.3 config chain has no `config.toml` | `services/config.py` `RuntimeConfig` resolves default DPI through CLI → `ARCAVEX_DPI` → `project.yaml` (`dpi:`) → `config.toml` → per-format default; wired into project + direct render; `doctor` reports the resolved source. | `test_config.py` (each level), `test_config_toml_dpi_reaches_render`, `test_project_yaml_dpi_beats_config` |
| **P3** `timings_ms` always empty | `_render_all` times compile+render; `_finalize` records `{compile_ms, render_ms}`. | `test_manifest_timings_are_populated` |
| **P3** batch has no aggregate summary | CLI prints `N ok / M failed (…)`. | CLI transcript |

New diagnostic code **ARC-RUN-002** registered in the catalog + `docs/diagnostics/ARC-RUN-002.md`
(mirror/coverage/orphan tests pass).

## Verification transcript

Gates (repo root, `.venv`):

```
pytest tests -q                         → 450 passed
ruff check src tests                    → All checks passed!
mypy src/arcavex/kernel --strict        → Success: no issues found in 12 source files
importlinter.cli lint                   → exit 0 (kernel imports no service/builtin)
```

Acceptance commands (isolated `ARCAVEX_HOME`, real `arcavex.exe`):

```
validate --project proj                 → OK template is valid            (DX-1)
render   --project proj                 → run …_89f185, 2 outputs
list-runs --project proj                → 1 project run listed
rerun proj/outputs/<run>                → Reproduced … (byte-identical)    ← determinism
diff <green-run> <blue-run>             → dssim ~0.24 + metadata: overrides / overrides.hash  (CR-1/DX-2)
project upgrade --to 2.0.0 --project proj
    stale override paths: nodes.background.style.fill (node background) project.patch[0]   (DX-5)
    node changes: added: backdrop / removed: background                  (DX-4 structural)
    preview diff: proj.square.png dssim 0.2429 (override dropped: stale)  (DX-4 perceptual)
doctor | config                         → config.toml present/absent + default dpi [source]  (DX-8)
list-runs --path outputs                → direct-mode --record run listed  (DX-7)
```

Determinism re-check (must still hold — confirmed):

- **Rerun byte-identity** — `rerun` reproduces the recorded outputs byte-for-byte on the same
  engine + platform (`Reproduced … (byte-identical)`); the patch hash added to the run-id
  fingerprint does not enter image bytes.
- **Patch-drift rerun** — editing `overrides/…patch.yaml` then rerunning: `reproduced:false`,
  `ARC-RUN-002`, `changed on disk: overrides (…)`, `reproduction.json input_drift`.
- **Batch serial == parallel** — 3 projects, `--jobs 1` vs `--jobs 4`: all 6 output sha256
  identical (checked in a script over `proj/*/outputs/*/*.png`).

## Scrutiny pointers

- `orchestrator._patch_input_ref` / `_finalize` — patch InputRef and its inclusion in the
  fingerprint; `_detect_drift` compares old vs freshly-recomputed manifest (data never drifts on
  rerun because the snapshot is authoritative — intentional).
- `runs._diff_metadata` — `overrides`/`overrides.hash` and `asset[<path>]` rows.
- `orchestrator._stale_patch_paths` — probes each op against `_authored_node_ids` (pre-repeat
  authored ids), so it finds *all* stale ops, not just the first compile failure.
- `api.Facade.validate_project` / `preview_project` + `ProjectInputs` (a dataclass, not a pydantic
  model, so ruamel line info survives for `ARC-TPL-092`).
- `services/config.py` precedence order and `doctor._check_config`.
- Test-shape update: `test_doctor.py` expected-check set now includes `config` (a new probe row,
  not a weakened assertion).

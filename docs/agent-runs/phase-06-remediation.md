# Phase 06 remediation — trusted local extension SDK

**Base reviewed:** Phase 6 (`85ac479`). **Reviews addressed:** `phase-06-code-review.md`
(CR-1..CR-5), `phase-06-dx-design-review.md` (DX-1..DX-8).
**Scope rule:** root-cause fixes, no weakening of tests/acceptance, all trust-boundary language
kept non-sandbox (spec §7.3). CR-5 (stray run dirs) was already fixed by the orchestrator and is
not re-touched here.

## Verdict

All P1/P2/P3 findings addressed. `ext scaffold` now emits a working, validate-green,
test-green extension for **every** documented kind; a component name colliding with a built-in or
another added extension is caught at `ext validate` **and** `ext add` with `ARC-EXT-001` naming
both providers; the loader names the incumbent by extension (CR-3). Full suite **530 passed**,
ruff clean, mypy-strict kernel clean, import-linter clean.

## Finding → action → test

| Finding | Action | Proof |
|---|---|---|
| **DX-1 / CR-1 (P1)** scaffold only valid for `effect`; 6/8 kinds ship non-instantiable stubs, `mask` has no golden test | Rewrote `scaffold.py`: every kind (`effect, mask, shape, exporter, template_function, decoder, backend, layout_solver`) gets a real, minimal, deterministic component **and** a matching `golden_test.py`. `backend`/`layout_solver` read their input document structurally and produce a real surface / `LayoutDocument`; both are honestly documented as forward-looking (v1 selects the built-in backend/solver). An `assert set(_MODULES)==set(COMPONENT_KINDS)` keeps the set complete. | `test_scaffold_every_kind_validates_and_tests` (parametrized over all 8); live scaffold+validate+test transcript below |
| **DX-2 (P1)** built-in name collision silently accepted at validate/add, only surfaces at `ext list`/render | New `collision.py`; `validate_extension(…, taken=…)` runs the collision gate. `ExtensionService` builds the taken-map (built-ins injected by bootstrap + other added extensions from state) and passes it at **validate, add, enable, and test**. Collision → `ARC-EXT-001`, exit 1, at the introducing command. | `test_collision_with_builtin_caught_at_validate_and_add`, `test_service_rejects_builtin_collision`, `test_validate_collision_with_builtin_names` |
| **CR-3 (P3)** duplicate names incumbent by class, not extension | Collision diagnostic labels the incumbent `built-in 'name'` or `extension 'ext-name'`. Loader threads a shared provenance map so the same holds at engine start. | `test_service_add_rejects_collision_with_other_extension` (asserts `extension 'ext-a'`); loader probe naming `alpha-ext` |
| **DX-4 (P2)** `save_png`/`load_png` raise raw `AttributeError` on a `str` path | Both coerce `Path(path)` first; signature is `Path \| str`. | `test_save_and_load_png_accept_str_path` |
| **DX-5 (P2)** scaffolded golden test has no committed-golden/`--update` workflow | Effect `golden_test.py` ships the `golden/<name>.png` + `--update` regeneration workflow (mirrors the reference example); passes on determinism+bounds until a golden is committed, then checks it. | `test_golden_update_workflow` |
| **DX-6 (P3)** guide/hint say `save` regenerates the golden (not runnable) | Guide, `ARC-EXT-051` hint (catalog + doc page), and the `GoldenHarness.check` diagnostic now say `python golden_test.py --update`. | doc page regenerated; guide diff |
| **DX-7 (P2)** `ext test` alone skips import/determinism/schema gates → false green | `test_extension` re-runs `validate` first and returns its diagnostics on failure before the golden subprocess. Guide documents it. | `test_ext_test_implies_validate` (disallowed import fails `ext test`) |
| **DX-8 (P3)** guide tutorial scaffolds `paper-texture`, colliding with the reference example | Guide workflow uses `./my-effect` / `my-effect`. | guide diff |
| **DX-3 / CR-4 (P2)** SDK table under-documents `__all__`; `dir(sdk)` leaks submodules + confusable `component_kinds` vs `COMPONENT_KINDS`; `register_component`/`Registries` dead author surface | Added `__dir__` returning `sorted(__all__)` (submodule leakage gone); removed `component_kinds` from the SDK surface (kept `COMPONENT_KINDS`); guide table expanded to the real `__all__` incl. `EffectKind` and the layout output types, and notes `register_component` is loader-facing with no `Registries` handle for authors. | `dir(sdk)==sorted(__all__)` probe; star-import probe |
| **CR-2 (P3)** determinism lint is shallow; guide implies exhaustive | Guide determinism section + `ARC-EXT-031` (catalog + doc page) now state it is a best-effort AST heuristic and a clean result is a reliability aid, not a guarantee — framed within the trusted-local-code posture. | guide/catalog diff |

## SDK surface change (enabling the two document-IR kinds)

`arcavex.sdk` now re-exports `LayoutDocument`, `LayoutNode`, `ResolvedCanvas` — the output types a
`LayoutSolver` must **produce** and a `RendererBackend` consumes, so those two kinds are genuinely
authorable. This stays within the SDK import contract (`kernel.ir` is permitted; services/builtin/
clients/bootstrap remain forbidden — import-linter passes). The compiled-document authoring types
are deliberately *not* exposed: a component reads its input document structurally.

## All-8-kinds proof (live)

```
kind                 validate  test
effect               OK        exit 0
mask                 OK        exit 0
shape                OK        exit 0
exporter             OK        exit 0
template_function    OK        exit 0
decoder              OK        exit 0
backend              OK        exit 0
layout_solver        OK        exit 0
```

## Guide-verbatim transcript (fresh ARCAVEX_HOME)

```
$ arcavex ext scaffold effect ./my-effect
Created my-effect (effect 'my-effect') — validate, test, then add it            (exit 0)
$ arcavex ext validate ./my-effect
OK my-effect — components: my-effect                                            (exit 0)
$ arcavex ext test ./my-effect
OK: deterministic and bounds-honest (no committed golden yet — run
'python golden_test.py --update' to add one) / PASS my-effect golden test       (exit 0)
$ arcavex ext add ./my-effect       → Added my-effect (enable it next)          (exit 0)
$ arcavex ext enable my-effect      → Enabled my-effect (active on the next run) (exit 0)
$ arcavex ext list                  → my-effect 0.1.0 enabled — effect:my-effect(exit 0)
$ arcavex ext disable my-effect     → Disabled my-effect (inactive next run)    (exit 0)
$ python my-effect/golden_test.py --update  → wrote golden .../my-effect.png    (exit 0)
$ arcavex ext test my-effect        → matches golden / PASS                     (exit 0)
# reference example
$ arcavex ext validate examples/extensions/paper-texture   → OK                 (exit 0)
$ arcavex ext test     examples/extensions/paper-texture   → matches golden/PASS (exit 0)
```

Collision (fresh home), component named after built-in `blur`:
```
$ arcavex ext validate ./dup  → ARC-EXT-001 Duplicate effect component 'blur':
    already provided by built-in 'blur', cannot also register 'dup-fx''s DupFx  (exit 1)
$ arcavex ext add      ./dup  → ARC-EXT-001 …                                    (exit 1)
```

## Final verification (once)

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest tests` | **530 passed**, exit 0 |
| Lint | `ruff check src tests` | All checks passed |
| Types | `mypy src/arcavex/kernel --strict` | Success (12 files) |
| Contracts | `importlinter.cli lint` | exit 0 (SDK boundary incl. new layout re-exports kept) |
| E2E exit criterion | `test_full_extension_lifecycle_and_render` | pass (scaffold→validate→test→add→enable→render, no core change) |

Note (unchanged from Phase 6): `mypy --strict` over `sdk/`+`services/` cannot run under this
interpreter because numpy's bundled `.pyi` uses a 3.12+ `type` statement — a pre-existing tooling
limitation, not introduced here. The kernel gate is strict-clean.

## Scrutiny pointers

- `services/extensions/scaffold.py` — the 8 component/golden-test builders; each golden test only
  exercises what its stub supports and checks determinism, so a fresh scaffold of any kind is
  green without hand-editing.
- `services/extensions/collision.py` + `service.py::_taken_names` — the taken-map (built-ins
  labelled `built-in 'x'`, siblings `extension 'y'`), excluding the extension under check so a
  re-add never self-collides.
- `loader.py::_register_one` — shared provenance for the incumbent-extension label; standalone
  `register_extension` calls fall back to `a built-in` (the loader's real path shares the map).
- `sdk/__init__.py` — `__dir__` narrowing + the three new layout re-exports; confirm the SDK
  import contract still holds.

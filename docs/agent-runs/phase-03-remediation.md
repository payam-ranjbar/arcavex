# Phase 03 remediation — effects, styles, shapes

Agent: Opus remediation lane. Base commit `0d051d7`. Machine: Windows 11,
`.venv\Scripts\python.exe` / `arcavex.exe`. Root-cause fixes only; no tests or acceptance
criteria weakened.

## Finding → action → test

| # | Finding (source) | Action | Regression test |
|---|---|---|---|
| CR-2 / DX-2 (P1) | `--style` documented but exposed by no command | Added `--style` to `render`, `validate`, `preview`, `template check`; threaded `style=` through the facade and the watch loop. A CLI local-file ref resolves relative to the invocation dir (what `./file.yaml` means on a command line); a template `style:` file ref stays template-relative. `--help` text added. | `tests/e2e/test_cli.py::test_render_with_style_flag_name_version`, `::test_render_with_style_flag_local_file`; `tests/unit/test_styles.py::test_style_cli_local_file_resolves_from_cwd` |
| DX-1 (P1) | pop-art-grid muddy — `posterize(5)` before `halftone` flattened tonal gradation, and the `duotone` compressed luminance so light areas still made big dots | Reworked the per-cell chain to `grade → halftone → grain`. Root cause was deeper than posterize: halftone reads *luminance* and discards colour, so the low-luminance duotone highlights kept the light background dotted-over. Dropping both posterize and duotone lets halftone read a graded full-tone source; all four cells now read as clear portraits on their panel colours. warhol_3's low contrast resolved by the bright-panel/dark-ink pairing (no palette edit needed). Golden regenerated. | `tests/golden/test_goldens.py::test_pop_art_grid_golden` (regenerated + byte-identical) |
| DX-3 (P2) | `style list`/`inspect` JSON lacked `response_version` | Added `response_version` to `StyleListReport` and `StyleInspectReport`. | `tests/unit/test_styles.py::test_style_reports_carry_response_version`; e2e `test_effects_list_json` asserts the same envelope on the new command |
| CR-1 (P2) | Composite `backdrop` always `None`, docstring claimed it was live | Took the smaller correct option (populating needs a CTM-correct canvas readback larger than Phase 3 warrants): narrowed the `CompositeContext.backdrop` docstring + backend construction comment to state it is a **deferred accessor returning None in v1**; added a `docs/backlog.md` entry and a ledger note. No claim it works. | — (doc/honesty change) |
| CR-3 / DX-7 (P2) | `ARC-STY-001` unlocated | Threaded the `style:` key's `(file, keypath, line)` through `StyleResolver.resolve`/`_find_library` into every `ARC-STY-001` raise (template refs only; a CLI `--style` has no source line). | `tests/unit/test_styles.py::test_unknown_template_style_is_located` |
| DX-6 (P2) | No effect param discovery | Added `facade.list_effects()` (parallels `list_styles`) and `arcavex effects list [--json]` / `effects inspect NAME`; introspects each pydantic schema into name/category/type/default/range (length + colour surfaced by validator, not raw `number`/`array`). README "Effects reference" table added. | `tests/unit/test_effects.py::test_list_effects_reports_schema`; `tests/e2e/test_cli.py::test_effects_list_json`, `::test_effects_inspect_unknown_exits_nonzero` |
| DX-4 (P2) | Effect lengths rejected `px` | `_as_pt` now accepts `px` and converts against the canvas DPI passed in the pydantic validation context (default 72 outside a compile); only relative `%` is still rejected (no basis). DPI threaded `compile → _parse_effects → _validate_effect` via `model_validate(..., context={"dpi": dpi})`. | `tests/unit/test_effects.py::test_effect_length_accepts_px`, `::test_effect_length_rejects_percent` |
| DX-5 (P2, disc.) | Param errors named only the first field | `_all_errors` lists every pydantic field error; wired into `ARC-FX-902` (effect/mask) and `ARC-FX-912` (shape). Catalog text updated + docs regenerated. | `tests/unit/test_effects.py::test_invalid_effect_params_lists_all_fields` |
| Effect visibility (disc.) | ink-bleed read as a no-op **and was backwards** — it used Skia `Dilate`, growing the *bright* value (paper into ink), the opposite of its name/docstring | Reimplemented as a masked grey-erosion that grows dark ink into lighter opaque neighbours, ignores transparent padding (no edge fringe), and leaves alpha untouched; it grows ink inward so it now declares **no** bounds expansion. Golden moved to the tonal fixture. edge-wear confirmed correct (not a no-op) and its golden strengthened (`amount 0.85`) so the distressed edge is visible. | `tests/unit/test_effects.py::test_ink_bleed_grows_dark_ink_not_light`; honesty entry flipped to `expands=False`; `effect-ink-bleed`/`effect-edge-wear` goldens regenerated |
| CR-5 (disc.) | channel-offset colour leak untestable (bounds-honesty only watches alpha, which it never touches) | Added a direct test: the R/B split is real and alpha (the silhouette) is preserved bit-for-bit, so no colour leaks the shape outward. | `tests/unit/test_effects.py::test_channel_offset_splits_rgb_and_keeps_alpha` |
| CR-4 (disc.) | Stale docstrings | `EffectSpec` (“contract-only in Phase 0; not executed” → now executes); Grain/Noise (“added to opaque pixels” → adds to all RGB, alpha untouched). | covered by existing effect tests |
| Docs | README claimed effects/styles are rejected (`ARC-FX-900`, `ARC-TPL-093/094`); no `--style`/`effects` in tables | Removed stale limitation, updated the two stale paragraphs, added `--style`/`effects` command rows, effects-reference table, px note, and a text-over-texture legibility note (DX-8). | `tests/unit/test_explain.py` mirror/coverage |

## pop-art-grid before → after (visual)

- **Before** (`0d051d7`): four `grade → duotone → posterize(5) → halftone → grain` cells. Only the
  orange (warhol_4) cell read as a face; cyan/purple/yellow were diffuse dot blobs — the
  posterize flattened gradation and the low-luminance duotone highlights kept the light
  background dotted over, so no head/background separation.
- **After**: `grade → halftone → grain`. All four cells read as clear head-and-shoulders
  portraits — the graded light background makes small dots that let the panel colour show around
  the head, features come through as dense dots, and the four panels (cyan, purple, yellow,
  amber) with per-cell halftone angle read as a genuine Warhol grid. Verified with the Read tool
  at full resolution; golden regenerated and byte-identical across two renders
  (`d3146145…`, 1.9 s warm, well under the 8 s guard).

## Verification transcript

```
pytest tests -q                         exit 0   (386 tests, was 373; +13 regression tests)
ruff check src tests                    All checks passed!
mypy src/arcavex/kernel --strict        Success: no issues found in 12 source files
importlinter.cli lint                   exit 0   (contracts kept)
pytest tests/golden -q                  exit 0   (21 goldens; pop-art/ink-bleed/edge-wear regen)
render pop-art-grid (square)            Rendered, sha d3146145…  (byte-identical x2)
render --style pop-art@0.1.0            Rendered
render --style ./library-seed/…/0.1.0.yaml (cwd-relative)   Rendered
validate pop-art-grid                   OK template is valid
style list --json / inspect --json      response_version: 1 present
effects list --json                     15 effects, versioned; halftone.params include pitch:length
seeded failures (validate):
  unknown effect   -> exit 1  ARC-FX-910
  invalid params   -> exit 1  ARC-FX-902
  unknown style    -> exit 1  ARC-STY-001 (now located: file, line, at style)
  unknown preset   -> exit 1  ARC-STY-010
  unknown role     -> exit 1  ARC-STY-011
```

## To double-check on re-review

- **ink-bleed golden** is on the smooth radial-gradient fixture, so the (now correct) dark growth
  reads subtly — the direction/behaviour is locked by a hard-edged unit test rather than by
  eyeballing the golden. If a stronger showcase is wanted, a fixture with hard ink edges would
  make it dramatic; deferred as not worth a new fixture.
- **Composite backdrop** is deliberately still `None` (CR-1 deferred, backlog logged) — this is an
  honest deferral, not a fix. Any future composite effect reading `backdrop` gets `None`.
- **duotone dropped from pop-art-grid**: the color stage (grade/duotone/posterize + fusion) is
  still exercised by the `fused-color-chain` and per-effect goldons; the pop-art example is now a
  focused halftone showcase.

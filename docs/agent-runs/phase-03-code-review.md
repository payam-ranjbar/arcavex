# Phase 03 code review — effects and styles

Reviewer: adversarial Opus review agent. Diff base `0cb9d09..0d051d7`.
Machine: Windows 11, `.venv\Scripts\python.exe` / `arcavex.exe`.

## Verdict

**ACCEPT with minor follow-ups.** Every Phase 3 exit criterion is met and verified by
execution: pop-art grid golden passes and is byte-identical across runs (1.7–2.1 s, well under
the 8 s guard); effect bounds-honesty tests are green; halftone is a genuine SkSL
`RuntimeEffect`; consecutive color effects fuse into one matrix and the fusion is proven
equivalent to sequential application; the style-pack resolution order holds with `--resolved`
provenance including the style layer; renders are deterministic. No P0/P1 defects. Two P2
gaps (both latent / non-blocking) and a handful of P3 doc/rigor nits, below.

## Gates (all green)

| Gate | Result |
|---|---|
| `pytest tests` | **373 passed** in 44 s |
| `ruff check src tests` | All checks passed |
| `mypy src/arcavex/kernel --strict` | Success, 12 files |
| `import-linter` (`importlinter.cli lint`) | Contracts kept, exit 0 |
| golden suite (`pytest tests/golden`) | 20 passed in 5 s |

## What was verified by execution

- **Determinism.** `effect_rng = np.default_rng(sha256(seed,node_id,effect_index)[:8])`
  (`effects_core/context.py:98`), not Python `hash()`; grep of `effects_core/` finds no
  `random`/`time`/`hash(`/`datetime` use. Pop-art render byte-identical twice
  (sha `e7a6d127…`). Grain with different node ids → different noise (test) .
- **Color fusion.** `_fuse_colors` collapses adjacent matrices via real 5×5 composition
  (`pipeline.py:102`); `build_color_filter` composes the remainder into one Skia filter.
  `test_fusion_is_semantically_equivalent` shows fused == sequential within ±2/255.
- **Premultiplied alpha (§3.1.3).** Probed directly: `image_to_rgba`/`rgba_to_image`
  round-trip preserves straight alpha `[255,0,0,128]`; duotone on a 50%-alpha red pixel keeps
  alpha 128 and yields a mid color `[74,46,40]` — **no fringing / darkening**. Skia's
  `ColorFilters.Matrix` un/re-premultiplies as the code documents.
- **Halftone is SkSL.** `Halftone._effect = skia.RuntimeEffect.MakeForShader(_HALFTONE_SKSL)`
  (`raster.py:216`); amplitude-modulated dot screen, pitch in px, angle rotation. Visually
  correct in the pop-art render (four distinct screen angles).
- **Surface pool (§4.5).** Leak guard asserts `outstanding == 0` after each render; the 4-effect
  chain test confirms `reused >= 1`. Verified green.
- **Bounds honesty.** `_effect_expansion` sums per-side declared insets;
  `render_bounds = bounds.expanded(...)`, `paint_bounds` = post-rotation AABB. Per-effect test
  asserts nothing paints outside `paint_bounds` (±2 px AA) and expanding effects fill their ring.
- **14/15 effects, shapes, styles.** All effect param errors located (ARC-FX-902), unknown
  effect → ARC-FX-910 listing registered effects, geometry-on-text → ARC-FX-911, unknown
  shape/params → ARC-FX-913/912, unknown style/preset/role → ARC-STY-001/010/011 with
  alternatives listed. `segno` pinned; QR deterministic. Style `name@version` resolves from
  `library-seed/styles`; `style list/inspect --json` work; `--resolved` shows
  `style=pop-art@0.1.0`.
- **Carry-overs RR2-4…12.** RR2-4 (dir-name fallback), RR2-5 (ARC-LAY-051 message rephrased,
  `solver.py:634/646`), RR2-7 (`_FIT_WIDTH_MARGIN` comment now honest), RR2-8 (fill
  redistribute), RR2-9 (backdrop-only containment suppression), RR2-10 (losing-layer value),
  RR2-11 (`set` adds absent optional field, `overlays.py:159`), RR2-12 (hint no longer lists
  line_height) — all present; test_phase03_carryovers covers 4/8/9/10/12, the rest verified in
  code. RR2-6 is a README edit.
- **Regression.** IPEN en/fa in square and a4, hello-poster (square) all render ok.
- **Architecture.** Kernel stays pure (import-linter green); effects/shapes resolve only via the
  injected registries in `SkiaBackend`; no second shaper (text still via `TextService`).

## Findings

### CR-1 (P2) — Composite `backdrop` snapshot is never provided (always `None`)
`backend.py:202` constructs `CompositeContext(image, None, …)` unconditionally, and
`_draw_with_effects` never builds the "content painted below in z-order" snapshot the spec
§3.2 / brief item 4 require. `context.py:203` documents `backdrop` as "the content already
painted below the node in z-order … or None when nothing is below" — but it is **always** None,
so the docstring is misleading. No functional impact today: the two shipped composite effects
(drop-shadow, glow) build from the element's own alpha and ignore `backdrop`. This is a latent
SPI-contract gap — any future/extension composite effect that reads the backdrop silently gets
nothing. (A strict reading of the spec contract would rate this P1; I keep it P2 because zero
shipped behavior depends on it.) **Fix:** either snapshot the backing content into
`CompositeContext.backdrop`, or narrow the docstring and note the deferral explicitly.

### CR-2 (P2) — CLI `render`/`validate`/`preview` expose no `--style` flag
`facade.render_file`/`compile` accept `style=` (spec §3.7) and the compiler fully honors a CLI
override (`test_style_cli_overrides_template` passes), but `clients/cli.py` never declares a
`--style` option and never passes `style=` through. `arcavex render … --style pop-art` fails
with a Typer usage error ("No such option: --style", exit 2). The primary opt-in (`style:` in
the template) works, so this is a convenience/override gap, not a broken feature. **Fix:** add
`--style` to `render`, `validate`, `preview` and thread it into the facade calls.

### CR-3 (P3) — Unknown-style error (ARC-STY-001) is not located
When a template's `style:` names a missing pack, `StyleResolver._find_library` raises
ARC-STY-001 with only a hint (`style.py:154`), no file/keypath/line — unlike the preset/role
errors (ARC-STY-010/011), which point at the node. The malformed-ref case
(`compiler.py:785`) is located, but the not-found case is not. **Fix:** pass the `style:` key's
source location through `resolve()` into the diagnostic.

### CR-4 (P3) — Stale / imprecise docstrings
- `models.py:171` `EffectSpec` — "contract-only in Phase 0; not executed" is now false;
  effects execute in Phase 3.
- `raster.py` Grain/Noise docstrings say noise is added "to opaque pixels", but the code adds
  it to all RGB regardless of alpha (harmless — transparent pixels stay invisible — but the
  comment overstates).

### CR-5 (P3) — Golden/honesty rigor caveats (no action required, documented)
- `channel-offset` shifts only R/B via `np.roll` (wraps at the padded-surface edge). The
  bounds-honesty test checks the **alpha** channel outside `paint_bounds`, but channel-offset
  never touches alpha, so that test cannot detect a colour leak from this effect. Low risk
  (offset ≪ padding), worth a note.
- The bounds "not-absurdly-large" assertion only requires *some* painted pixel in the expansion
  ring, so an over-declared inset would still pass. Acceptable for v1; tolerance is documented.
- SSIM is a whole-image mean; the probe scenes carry a full opaque background plus a 55–68 %
  subject, so real regressions do move well past dssim 0.003 — the mapping (DSSIM=(1−SSIM)/2,
  threshold 0.003 ⇔ SSIM≥0.994) is documented and calibrated in `harness.py`.

## Commands run

```
git diff 0cb9d09..0d051d7 --stat
.venv\Scripts\python.exe -m pytest tests -q                       # 373 passed
.venv\Scripts\python.exe -m ruff check src tests                  # clean
.venv\Scripts\python.exe -m mypy src/arcavex/kernel --strict      # clean
.venv\Scripts\python.exe -m importlinter.cli lint                 # exit 0
.venv\Scripts\python.exe -m pytest tests/golden -q                # 20 passed, 5s
arcavex render examples/pop-art-grid/template.yaml --data … -f square   # ok, 2.1s, byte-identical x2
arcavex style list --json ; style inspect pop-art --json          # ok
arcavex validate examples/pop-art-grid/template.yaml --data …     # ok
arcavex render … --style pop-art                                  # usage error (CR-2)
# seeded failures: unknown effect/params/style/preset/role, geometry-on-text — all located
# regression: ipen en/fa square+a4, hello-poster square — all ok
# premul probe + collect_plan fusion check — as described above
```

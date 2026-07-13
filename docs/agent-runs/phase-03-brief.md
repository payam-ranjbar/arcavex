# Phase 03 brief — Effects and styles (spec §11 Phase 3)

## Scope

1. **Effect pipeline** (§4.4, §3.2): authored ordered `effects:` list per node compiled into the
   internal category-aware plan `geometry → fused color → ordered raster → composite`.
   - `Effect` SPI live: kind (GEOMETRY|COLOR|RASTER|COMPOSITE), pydantic param_schema,
     MANDATORY `bounds_expansion(params) -> Insets` (zero allowed, honesty tested),
     `apply(ctx)`.
   - EffectContext per category exactly per spec §3.2 table: geometry gets Path2D+params+rng;
     color returns a ColorTransform (4x5 matrix or LUT) and consecutive color effects FUSE
     into one application; raster gets input surface + params + rng, allocates only from the
     surface pool; composite gets element surface + read-only backdrop snapshot (content
     painted below in z-order).
   - Seeded RNG tree: `hash(document.seed, node.id, effect_index)` (stable digest-based, not
     Python hash()); no `random`, no wall clock (add a lint/validation check for extensions
     later — for built-ins, code review enforces).
   - `paint_bounds` = layout bounds + accumulated bounds_expansion; renderer allocates and
     composites accordingly (a drop-shadow must not be clipped).
   - Invalid effect name → located error listing registered effects; invalid params → located
     error from the param schema (required seeded failure: "invalid effect parameters").
2. **Built-in effects** (`builtin/effects_core/`) — ALL of spec §4.4's v1 list:
   blur (raster, skia ImageFilter), drop-shadow (composite), glow (composite),
   duotone (color), threshold (color), grade (color: lift/gamma/gain or
   brightness/contrast/saturation), posterize + palette-map (color), grain (raster, seeded),
   noise (raster, seeded), ink-bleed (raster), halftone (raster via SkSL RuntimeEffect —
   dot-screen with pitch + angle params), channel-offset (raster), torn-paper (geometry,
   seeded edge displacement on the node path), edge-wear (raster, seeded).
   Implementation notes: color effects as 4x5 matrices/LUTs so fusion is real; SkSL preferred
   where natural (halftone required in SkSL per spec exit criteria); raster effects operate on
   node-local surfaces from a pooled allocator (simple pool: dict by size bucket, lifetime =
   one pipeline run, §4.5).
3. **Shapes** (`builtin/shapes_core/`, ShapeGenerator SPI live): starburst(points, inner_ratio),
   speech_bubble(corner, tail), qr_code(data, quiet_zone) using `segno` (pure-python,
   deterministic — add as dependency). `type: shape, generator: name, params: {...}`.
4. **Style packs** (§4.1.3): YAML bundle: version, palettes, fonts (role → family stack),
   effect_presets (name → {name, params}), shape_presets, role defaults (heading/body/accent
   → style fields). Sources: local file path (`style: ./pop-art.yaml`) or library
   `name@version` from `library-seed/styles/` + `$ARCAVEX_HOME/styles/` (full library
   publishing is Phase 4; reading versioned dirs is enough now).
   - Template opt-in `style:`; nodes reference `style_role: heading` and
     `effect_preset: halftone`; palette colors addressable as `{{ palette.warhol_1[0] }}`.
   - Resolution order (§4.1.4): style defaults → template values → format patch → locale
     patch. `--resolved` provenance includes the style layer.
   - Unknown style ref / preset / role → located errors listing available.
   - `arcavex style list` / `arcavex style inspect NAME` (--json) per §3.7 (list_styles,
     inspect_style).
5. **Golden-image test infrastructure** (§8.5): perceptual diff via SSIM (numpy
   implementation; threshold aligned to spec dssim ≤ 0.003 — document the mapping/calibration
   in the test module); per-platform golden dirs `tests/golden/goldens/<platform-tag>/`;
   `ARCAVEX_UPDATE_GOLDENS=1` (+ make target) regeneration; failure artifact dump (actual +
   diff heatmap PNG) into outputs-tmp/golden-failures/. Goldens for: each effect on a fixture
   scene (14), one fused-color-chain case, halftone SkSL, masks (existing pixel tests may
   migrate), ipen fa/en square, pop-art grid.
6. **Golden case #3**: `examples/pop-art-grid/` — Warhol-style N×M grid built with repeat over
   palette variants of one source image (use examples/reference/logo.png copy or a generated
   fixture image): per-cell posterize/duotone with palette-map + halftone, style pack
   `pop-art` (library-seed/styles/pop-art/0.1.0.yaml) supplying palettes/fonts/presets, title
   in display role. Must demonstrate: style opt-in, effect presets, per-cell effect param
   variation via expressions, seeded grain determinism.
7. **Effect bounds honesty tests** (§8.5): for each effect, render a probe node tightly and
   with padded canvas; assert pixels outside declared paint_bounds are untouched and pixels
   inside match — i.e. declared expansion is neither lying small nor absurdly large (tolerance
   documented).
8. **Perf guard**: pop-art grid (1080²) renders < 8s warm on this machine; note actuals.

## Carry-over (phase-02 re-review P3s — fix all in this phase)

- RR2-4: rendering `template.yaml` from inside its own directory must not yield a hidden
  `.square.fa.png` (empty stem) — fall back to the directory name.
- RR2-5: ARC-LAY-051 sub-line message mislabels full-text height as "one line is Xpt".
- RR2-6: README intro still shows the default output name without the locale segment.
- RR2-7: _FIT_WIDTH_MARGIN comment misattributes the cause (~500x off quantization claim);
  investigate the real SkParagraph re-layout sensitivity or fix the comment honestly.
- RR2-8: stack fill clamp does not redistribute freed space to other fill children.
- RR2-9: containment-based overlap suppression also hides genuinely swallowed non-backdrop
  siblings; refine (suppress only full-bleed/backdrop containers).
- RR2-10: `--resolved` shows only the final value on overridden ops; record what the losing
  layer set.
- RR2-11: patch `set` cannot add a schema-valid-but-absent optional field (e.g. flip
  direction on an undirected group); allow adding known-valid fields.
- RR2-12: ARC-TPL-051 hint lists line_height as valid while ARC-TPL-053 rejects it.
- Standing: phase-1 CR-13 canonical float form — due by Phase 4 at the latest; fixing here is
  welcome if touched.

## Non-goals

Projects/library publishing (Phase 4), MCP (5), extension loading (6), JPEG/WebP/PDF (7),
GPU, wide-gamut color. Do not build an authoring-visible effect graph (§12.12: list only).

## Constraints

- Kernel stays pure; effects_core/shapes_core are builtins (registry-registered via
  bootstrap); the renderer resolves effects only through the registry.
- Color policy: sRGB premultiplied (§3.1.3) — be careful with premultiplied alpha in color
  matrices (unpremultiply → apply → repremultiply where required; document).
- Determinism: same seed → byte-identical; different node ids → different noise.
- All existing tests stay green (update only where behavior legitimately changed).
- New diagnostic codes registered + documented (coverage tests).

## Acceptance commands

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\arcavex.exe render examples/pop-art-grid/template.yaml --data examples/pop-art-grid/data.yaml --format square -o outputs-tmp/popart.png
.venv\Scripts\arcavex.exe style list --json
.venv\Scripts\arcavex.exe style inspect pop-art --json
.venv\Scripts\arcavex.exe validate examples/pop-art-grid/template.yaml --data examples/pop-art-grid/data.yaml
```

Plus seeded failures: unknown effect, invalid effect params, unknown style, unknown preset,
unknown role — located, listed alternatives, correct exit codes.

## Exit criteria (spec Phase 3)

Pop-art grid golden case passes; effect bounds tests green; halftone is SkSL; color chains
fuse; style pack resolution order holds with provenance; renders deterministic.

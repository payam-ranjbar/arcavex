# pop-art-grid — golden case #3

A Warhol-style 2×2 grid: one source portrait repeated across four cells, each on a different
panel colour from the `pop-art` style pack and screened at a different halftone angle and ink. It
is the acceptance artifact for Phase 3's effect system, shape/style packs, and shader work.

## Render it

```bash
arcavex render examples/pop-art-grid/template.yaml \
  --data examples/pop-art-grid/data.yaml --format square -o popart.png

# Inspect the style pack it uses
arcavex style inspect pop-art --json
```

Rendering without `-o` writes the default `pop-art-grid.square.png`.

## What it exercises

| Feature | Where |
|---|---|
| Style opt-in (`style: pop-art@0.1`) | palettes, `effect_presets`, and the display `heading`/`accent` roles come from the pack |
| Palette in expressions | each cell's colours are `{{ palette[cell.palette][i] }}` |
| Per-cell effect variation | `repeat` over cells drives each cell's halftone `angle` and `ink` (a palette colour) by expression |
| Effect presets | the halftone and grain effects are referenced as `{preset: ...}` |
| Graded tonal source | `grade` spreads the portrait's tonal range so the dot screen tracks luminance instead of a flattened source |
| SkSL halftone | the dot-screen is a real runtime shader, its pitch DPI-aware |
| Seeded grain determinism | `seed: 41` makes every render byte-identical |
| Display-role text | the title uses the pack's `heading` role (`style_role: heading`) |

The `source.png` subject is a synthetic tonal portrait generated for this example (it has a full
luminance range so the halftone reads well); it is not the reference poster.

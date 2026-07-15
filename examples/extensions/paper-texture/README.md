# paper-texture — a reference Arcavex extension

A complete, reviewed **raster effect** extension: it lays seeded paper grain, soft fibre streaks,
and a warm tint over any node's raster. Use it as the worked example when writing your own
extension.

> **Trust boundary (spec §7.3).** A Python extension runs with the full permissions of the
> Arcavex process. It is **trusted local code**, not sandboxed. Validation catches compatibility
> and authoring mistakes, not malice — review an extension (including this one, and anything an AI
> hands you) like any other local dependency before you enable it.

## Files

| File | Purpose |
|---|---|
| `extension.toml` | Manifest: name, version, engine/IR floors, and the component list. |
| `component.py` | The `PaperTexture` effect. Imports **only** `arcavex.sdk`. |
| `golden_test.py` | The check `arcavex ext test` runs: determinism + golden output + bounds honesty. |
| `fixtures/input.png` | The input raster the golden test applies the effect to. |
| `golden/paper-texture.png` | The committed expected output (regenerate with `--update`). |

## What the effect demonstrates

- A typed pydantic **`param_schema`** (`grain`, `fibre`, `warmth`, all in `[0, 1]`).
- An **honest `bounds_expansion`**: the effect only recolours existing pixels and never touches
  alpha, so it declares `Insets()` (zero) — and the GoldenHarness proves it stays inside.
- **Determinism**: all randomness comes from the seeded `ctx.rng`, so a fixed document seed
  renders byte-identical output. It imports no `random` and reads no clock or files — the
  determinism lint would flag any of those.

## Use it from a template

Add and enable it, then reference the component by name from any node's `effects:` list:

```bash
arcavex ext validate examples/extensions/paper-texture
arcavex ext test     examples/extensions/paper-texture
arcavex ext add      examples/extensions/paper-texture
arcavex ext enable   paper-texture
```

```yaml
# in a template node
effects:
  - name: paper-texture
    params: {grain: 0.08, fibre: 0.12, warmth: 0.1}
```

Then render as usual — no change to Arcavex core is needed. Disabling takes effect on the next
run (the loader registers only enabled extensions at start).

## Regenerating the golden

After an intentional change to the look, regenerate the committed golden and review the image
diff before committing:

```bash
python examples/extensions/paper-texture/golden_test.py --update
```

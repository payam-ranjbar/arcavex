# Build the tool you need

The built-in vocabulary does not bound what you can make. If the art direction needs a treatment the
engine does not ship, **author it** — this is a designed-for path, not a workaround.

Requires a shell. Not available over MCP alone.

## First: check what exists

```bash
arcavex effects list      # every effect, built-in and installed
arcavex style list        # style packs and presets
arcavex font list         # families, bundled vs installed
```

The built-in set is larger than it looks. Do not hand-roll a blur.

## The loop

```bash
arcavex ext scaffold effect ./my-effect --name grain-warp
# edit ./my-effect/component.py
arcavex ext validate ./my-effect
arcavex ext test ./my-effect
arcavex ext add ./my-effect
arcavex ext enable grain-warp
arcavex effects list | grep grain-warp     # confirm it is discoverable
```

Then use it in a template like any built-in:

```yaml
effects:
  - name: grain-warp
    params: {amount: 0.4}
```

## What the scaffold gives you

A **working effect**, not a stub — it renders before you touch it, so you edit from a known-good
state. Plus a manifest and a golden test that already checks the two things easiest to get wrong:

- **Determinism** — the same seed must produce byte-identical output. Take all randomness from
  `ctx.rng`, never from `random` or the clock.
- **Bounds honesty** — `bounds_expansion` must declare how far outside the node you paint. Under-
  declare and your effect gets clipped; the harness catches it.

`ext test` passes on those two before you commit a golden image, so the loop closes early. Add a
golden once the look settles: `python golden_test.py --update`, then review the image before keeping it.

## Writing the component

Import **only** from `arcavex.sdk` — it re-exports every contract, helper, and value type an
extension may use. `ext validate` enforces this (`ARC-EXT-030`), so reaching into engine internals
fails loudly rather than breaking on the next release.

Effect kinds: **raster** (pixel pass over the node's image), **color** (a color transform, fusible),
**geometry** (path-level), **composite** (draws relative to the node, e.g. shadows).

A raster effect receives a `RasterContext` and returns an image:

```python
def apply(self, ctx: object) -> object:
    assert isinstance(ctx, RasterContext)
    rgba = image_to_rgba(ctx.image)      # numpy (h, w, 4) uint8
    ...                                   # your pass
    return rgba_to_image(rgba)
```

## When you cannot build it

If it needs engine capability that does not exist — a vector filter, a font feature, an unsupported
format — **say so plainly and plan around it.** Propose the nearest expressible direction and name
the gap. Never quietly drop part of the art direction because the tool was missing.

## Deliver the source

A custom effect is part of the deliverable. Hand over the extension directory with its golden
fixture, so the user can re-render and modify it later. An enabled-but-undelivered effect makes the
template unreproducible on any other machine.

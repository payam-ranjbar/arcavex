# Extension guide — trusted local extensions

Extensions are Arcavex's **engine-development** mechanism, not the normal template-authoring
mechanism (spec §7). An extension adds a new component — an effect, mask, shape, exporter, layout
solver, template function, renderer backend, or asset decoder — that the engine then treats
exactly like a built-in. You reach for one when you need a capability the built-ins do not provide
and a template cannot express; most work never needs one.

## Trust boundary — read this first

**A Python extension is trusted local code. It runs with the full permissions of the Arcavex
process, and Arcavex does not sandbox it. Validation catches compatibility and authoring mistakes,
never malice — review any extension you did not write, including one produced by an AI, like any
other local Python dependency before you enable it.**

This is not hedging; it is the security model (spec §7.3). The AST import scan, the determinism
lint, and the crash-contained subprocess test all exist to make an extension *reliable and
reproducible*, and none of them is a security barrier:

- The **import-surface** and **determinism** checks are *reproducibility* rules (spec §3.2). An
  effect that imports `random`, reads the wall clock, or reads an undeclared file produces output
  a rerun cannot reproduce — so validation flags it as an authoring error, not a threat.
- Running an extension's golden test in a **subprocess** contains a crash (a segfault or an
  exception) so it does not take down the engine. That is crash isolation for reliability, not
  confinement of hostile code.

A deliberately malicious enabled extension is explicitly **out of scope for v1** (spec §7.4). A
WASM- or OS-isolated worker runtime may be added later if real third-party extension distribution
requires it; it is not a prerequisite for AI-authored templates, local CLI use, or this SDK. The
render path itself remains network-free by design.

## The SDK — the only surface you import

An extension imports **only** `arcavex.sdk`. That package re-exports everything you may use;
reaching into `arcavex.kernel` internals, `arcavex.services`, `arcavex.builtin`, or
`arcavex.clients` is an authoring error the validator flags (`ARC-EXT-030`), and the same boundary
is enforced on the SDK itself by an import-linter contract.

| Group | What `arcavex.sdk` gives you |
|---|---|
| **Contracts (SPI)** | `Effect`, `MaskGenerator`, `ShapeGenerator`, `Exporter`, `LayoutSolver`, `TemplateFunction`, `RendererBackend`, `AssetDecoder` — subclass one per component. |
| **Effect contexts** | `GeometryContext`, `ColorContext`, `RasterContext`, `CompositeContext` — the input to each effect category's `apply`. |
| **Colour transforms** | `ColorMatrix`, `ColorTable`, `compose_color_matrices` — what a `COLOR` effect returns. |
| **Determinism** | `effect_rng` — the single seeded RNG-tree helper; draw *all* randomness from `ctx.rng`. |
| **Path / surface utilities** | `SurfacePool`, `render_to_pool`, `image_to_rgba`, `rgba_to_image`. |
| **Param helpers** | `BaseModel`, `ConfigDict`, `Field` (pydantic), plus the unit-aware `Points` and `RGBAColor` fields. |
| **IR value types** | `Rect`, `Insets`, `Dim`, `Matrix3`, `Unit`, `Color`, and the `Path2D` / `Surface` handle protocols. |
| **Registration** | `COMPONENT_KINDS`, `register_component` — the component-kind table, shared with the loader. |
| **Testing** | `GoldenHarness` — golden-fixture + bounds-expansion-honesty checks. |

## The manifest — `extension.toml`

One extension directory holds an `extension.toml` and its Python entry modules. The manifest names
the extension, the minimum engine and IR versions it targets, and a **list** of components (a
package may register several):

```toml
name = "print-effects"
version = "0.2.0"
ir_min = "1.0"
engine_min = "0.1"

[[components]]
kind = "effect"
name = "halftone-cmyk"
entry = "effects:HalftoneCMYK"

[[components]]
kind = "effect"
name = "ink-bleed"
entry = "effects:InkBleed"
```

- `kind` is one of `effect`, `mask`, `shape`, `exporter`, `layout_solver`, `template_function`,
  `backend`, `decoder`.
- `name` is the component's globally-unique name **per kind** — the authoring vocabulary a template
  uses. A duplicate (against a built-in or another extension) fails with `ARC-EXT-001` naming both
  providers.
- `entry` is `module:Class`, relative to the extension directory. A multi-file extension imports
  between its own modules with relative imports.
- Extension → extension dependencies are prohibited in v1.

## The workflow

```
scaffold → implement → validate → golden test → add → enable
```

```bash
arcavex ext scaffold effect ./paper-texture   # writes a working, valid starter
arcavex ext validate ./paper-texture          # manifest, compat, imports, determinism, schema, shader
arcavex ext test     ./paper-texture          # runs golden_test.py in a crash-contained subprocess
arcavex ext add      ./paper-texture          # validates, copies into the Arcavex home, recorded DISABLED
arcavex ext enable   paper-texture            # active on the next run
arcavex ext list                              # every added extension and its state
arcavex ext disable  paper-texture            # inactive on the next run
```

Lifecycle is `add → validate → disabled → enable` (spec §3.3): adding never enables, and
**disabling takes effect on the next process start** — the loader registers only enabled
extensions when the engine boots, so a disabled extension is simply not loaded next time. Built-ins
are always enabled.

Everything the CLI does is also available on the Python facade (`scaffold_extension`,
`validate_extension`, `test_extension`, `add_extension`, `enable_extension`, `disable_extension`,
`list_extensions`). Extension *authoring* is deliberately **not** exposed over MCP (spec §6.2) — it
is a CLI/API-only, engine-development activity.

## What validation checks

`arcavex ext validate` runs every gate and reports located `ARC-EXT` diagnostics:

- **Manifest shape** — valid TOML, required fields, valid `module:Class` entries
  (`ARC-EXT-010`…`014`).
- **Engine/IR compatibility** — `engine_min`/`ir_min` versus this build (`ARC-EXT-020`).
- **Imports** — every source file imports only `arcavex.sdk` (`ARC-EXT-030`).
- **Determinism** — no `import random`, no wall-clock read, no undeclared filesystem read in a
  component method (`ARC-EXT-031`).
- **Component wiring** — the entry class imports, subclasses the right contract, and its
  `name`/`format` attribute matches the manifest (`ARC-EXT-021`, `ARC-EXT-022`).
- **Parameter schema** — effects, masks, and shapes expose a valid pydantic `param_schema`
  (`ARC-EXT-023`).
- **Shaders** — a component that declares an SkSL source (a `SKSL` class attribute) has it compiled
  up front (`ARC-EXT-032`).

## The determinism rule

Identical inputs must produce identical output bytes on the same engine, platform, fonts, seed, and
options (spec §8.1). For an effect that means:

- **All randomness comes from `ctx.rng`** — the per-`(node, effect index)` generator seeded from
  the document seed. Never `import random`, never the clock.
- **No undeclared inputs** — do not read files or the environment inside a component method.

The lint enforces exactly this. It is a reproducibility rule, not a security check.

## Testing with `GoldenHarness`

Ship a `golden_test.py` (the scaffold writes one) that drives `GoldenHarness` and exits non-zero on
failure; `arcavex ext test` runs it in a subprocess. The harness does two things a plain equality
test cannot:

- **Output check** — renders your effect on a fixture with a fixed seed and compares to a committed
  golden image (`ARC-EXT-051` on mismatch); `save` regenerates the golden.
- **Bounds-expansion honesty** — a raster effect declares, via `bounds_expansion`, how far outward
  it paints so the layout solver can pre-grow the paint region. The harness renders the effect into
  a generously padded canvas, measures how far the *visible* output actually spreads, and fails
  (`ARC-EXT-050`) if the effect paints wider than it declares — because the real pipeline would clip
  that output. Declaring more than you use is only a note.

See `examples/extensions/paper-texture/` for a complete, reviewed effect that renders through a
template with no change to Arcavex core.

# Architecture

Arcavex is a **microkernel**: a small pure kernel defines the contracts and the document pipeline,
and everything replaceable — effects, masks, shapes, exporters, the layout solver, the renderer
backend, template functions, asset decoders — plugs in behind those contracts. Dependencies point
**inward** toward the kernel, never outward, and that direction is mechanically enforced by
import-linter contracts (spec §3, §12.18).

This page maps the layers, the pipeline, the SPI contracts, and the determinism and provenance
models. The public authoring surface those internals serve is [template-schema.md](template-schema.md)
and [cli.md](cli.md).

## Layer map

```
arcavex/
├── kernel/          # pure: IR, contracts (SPIs), registry, diagnostics, the pipeline + facade
│   ├── ir/          #   CompiledDocument / LayoutDocument, units, colors, canonical hashing
│   ├── contracts/   #   the 8 SPI ABCs + their value types
│   ├── registry/    #   component registries + bootstrap wiring
│   ├── diagnostics.py
│   └── api.py       #   the service facade (render_file, validate, inspect, patch, runs, …)
├── services/        # engine logic: template compiler, expressions, text stack, layout glue,
│                    #   assets/CAS, style, projects, library, orchestrator, runs, budgets, cache,
│                    #   doctor, explain, authoring, config, fsutil, diagnostics_catalog
├── builtin/         # the default components behind the contracts: backend_skia, effects_core,
│                    #   masks_core, shapes_core, layout_anchors, export_raster, export_pdf,
│                    #   template_fns
├── sdk/             # the single public surface a trusted extension imports (re-exports kernel)
├── clients/         # parse-and-present only: cli.py, mcp_server.py, watch.py
└── bootstrap.py     # the composition root: builds the registries and wires everything together
```

- **kernel** is pure — it imports nothing from `builtin`, `services`, `clients`, `sdk`, or
  `bootstrap`. It owns the IR (the compiled/layout document types, unit and color handling, and the
  canonical serializer that feeds every hash), the eight SPI contracts, the registry, the diagnostics
  model, and the pipeline/facade.
- **services** hold the engine logic (compile, expressions, text, layout orchestration, assets,
  projects, provenance, budgets). They resolve pluggable components through an **injected registry
  table** wired by bootstrap, so they never import the built-ins directly.
- **builtin** provides the default implementation of each contract. Built-ins face downward toward
  the kernel and the shared text service (the single shaper); they never reach up into a client or
  the composition root.
- **sdk** is the one public, downward-facing surface a trusted local extension imports. It re-exports
  the kernel contracts and IR value types and nothing upward — the same boundary the extension
  import-surface validator enforces on extension code.
- **clients** (CLI, MCP server) are parse-and-present only: they call the service facade through
  `kernel.api` and build one via `bootstrap`, and never reach into services or built-in internals.
- **bootstrap** is the composition root — the one place that assembles the concrete component
  registries and hands the facade its dependencies.

## The document-state pipeline

A render is a fixed sequence of state transitions, each producing an immutable document the next
stage consumes (spec §3.4). The orchestration lives in the facade (`kernel/api.py`) and the shared
pipeline (`services/pipeline.py`):

```
template + data  ──compile──▶  CompiledDocument  ──layout──▶  LayoutDocument  ──render──▶  raster surface  ──export──▶  file
                   (services/template)              (builtin/layout_anchors)   (builtin/backend_skia)      (builtin/export_*)
```

1. **Compile** — the template loader + expression evaluator + compiler resolve variables, expand
   `repeat`/`if` constructs, apply style → format → locale → project-override patch layers, and
   produce a `CompiledDocument` (fully-resolved node tree). Diagnostics here are authoring errors.
2. **Layout** — the anchor solver resolves each node's bounds from its constraints (anchors, sizes,
   stacks, fit policies), producing a `LayoutDocument` with concrete geometry. `layout inspect`
   surfaces this document.
3. **Render** — the Skia backend paints the layout document to a raster surface, running the effect
   pipeline (`geometry → fused color → raster → composite`) and masks through pooled surfaces.
4. **Export** — the exporter chosen by output extension writes the surface to PNG/JPEG/WebP/PDF via
   one shared atomic-write helper.

Per-render resource budgets (`ARC-RND-020..023`) are checked pre-flight from the canvas + DPI, before
any pixels are allocated, so a runaway render is refused rather than exhausting memory.

### The three boxes a laid-out node carries

`LayoutNode` records three rectangles, and confusing them is the source of most geometry bugs:

| Box | Space | Grown by | Used for |
|---|---|---|---|
| `bounds` | canvas pt, pre-rotation | nothing | anchoring, sizing, stacks — the authored layout box |
| `render_bounds` | node-local, pre-rotation | the effects' declared bounds expansion | the element surface the backend allocates, so a blur or tear is not clipped |
| `paint_bounds` | canvas pt | rotation **and** effect expansion | clipping, debug overlays, and the allocation envelope |

Effect expansion is an *allocation request*, not occupancy: a drop-shadow claims room it will
paint softly into, but the node's ink stays inside `bounds`. `paint_bounds` folds that request
together with the post-rotation AABB, which is real geometry. Overlap reporting therefore
classifies against the rotation AABB of `bounds` alone (`kind: content`) and treats an
intersection that exists only in `paint_bounds` as effect spill (`kind: halo`) — see
[cli.md](cli.md#overlap-kinds).

## SPI contracts

Eight service-provider interfaces define every replaceable component. An extension subclasses exactly
one per component (see [extension-guide.md](extension-guide.md)); the built-ins are just the shipped
implementations.

| Contract | Responsibility | Built-in(s) |
|---|---|---|
| `Effect` | Transform a node's geometry/color/raster/composite | `effects_core` (15 built-ins) |
| `MaskGenerator` | Produce a clip/alpha mask | `masks_core` (`rounded_rect`, `circle`, `diamond_grid`) |
| `ShapeGenerator` | Build a shape path | `shapes_core` (`starburst`, `speech_bubble`, `qr_code`) |
| `Exporter` | Encode a surface to a file format | `export_raster` (PNG/JPEG/WebP), `export_pdf` |
| `LayoutSolver` | Resolve constraints to geometry | `layout_anchors` |
| `TemplateFunction` | An expression function | `template_fns` (9 built-ins) |
| `RendererBackend` | Paint a layout document to a surface | `backend_skia` |
| `AssetDecoder` | Decode an ingested asset | (asset store, header-guarded) |

## The import-linter contracts

The layering above is not a convention — it is checked in CI (`make contracts` /
`importlinter.cli lint`). Five forbidden-import contracts from `pyproject.toml`:

| Contract | Rule |
|---|---|
| **Kernel is pure** | `arcavex.kernel` imports nothing from `builtin`, `services`, `clients`, `bootstrap`, or `sdk`. |
| **SDK imports only the kernel** | `arcavex.sdk` never reaches into `services`, `builtin`, `clients`, or `bootstrap`. |
| **Built-ins face downward** | `arcavex.builtin` never imports `clients` or `bootstrap`. |
| **Services stay off the built-ins** | `arcavex.services` never imports `builtin`, `bootstrap`, or `clients` (functions resolve through the injected registry). |
| **Clients are parse-and-present** | `cli` and `mcp_server` import only `kernel.api` + `bootstrap`, never `services`/`builtin` internals. |

## Determinism model

Correctness in Arcavex is *determinism*: identical inputs produce byte-identical outputs on the same
engine version and platform (spec §8.1). The structural guarantees:

- **Fonts are confined to the bundled set** — no system-font fallback, so shaping never varies by
  host.
- **All randomness flows from a seeded per-`(node, effect)` RNG tree** derived from the document seed
  (sha256), so effects like grain and noise reproduce exactly.
- **Canonical hashing** unifies int/float (`2` and `2.0` hash-equal) while keeping numbers distinct
  from strings; one shared serializer feeds template/style/data hashes, run manifests, and run ids.
- **Exported bytes carry no timestamps or run ids** — the PDF exporter strips `/CreationDate`,
  `/ModDate`, and `/ID`, embedding only stable metadata (engine version, render signature, sRGB
  policy). Timestamps live only in run manifests.
- **Atomic writes** (temp file + `os.replace`) for every output; an interrupted render publishes
  nothing, and completed run directories are immutable.

The byte-identical guarantee is structural, not a runtime check, so it carries no measurable
performance penalty (see [performance.md](performance.md)).

## Run and provenance model

A recorded render (`render --record`, or any project render) writes a run directory
`outputs/<timestamp>_<shorthash>/` with a `manifest.json` that pins **every input by hash** — engine
version, platform, IR version, the template/style/data hashes, the resolved snapshot, asset and font
hashes, the seed, the options, and the outputs. From that manifest:

- **`rerun`** reproduces the run into a new directory — byte-identical on the same engine + platform.
  If a recorded input drifted on disk it renders from the current inputs and names the drift
  (`ARC-RUN-002`) rather than silently differing, and it refuses to claim exact reproduction across a
  different engine version or platform.
- **`diff`** reports a per-output pixel/perceptual diff plus separate template/data/asset/font/engine/
  option/override change attribution.
- **`batch`** renders many projects across process-isolated parallel jobs with output byte-identical
  to a serial run.

Provenance is same-platform: cross-platform reproduction is perceptual, not bit-exact — see
[known-limitations.md](known-limitations.md).

## MCP parity

The MCP authoring server (`arcavex mcp serve`, spec §6.2) adds **no exclusive capability**. Every one
of its 25 tools is a thin wrapper over exactly one `kernel.api` facade method and returns the same
versioned pydantic result the CLI's `--json` returns — a schema-parity test asserts each tool's
output schema equals the facade model's JSON schema. The transport is stdio only; the render path is
network-free by design. The reverse containment is deliberate rather than accidental: the surface
carries the **discovery** commands an agent needs to author correctly (`style list`, `effects list`,
`font list` — the legal `style.font` vocabulary), while actions that install code or typefaces onto
the machine (`ext add`/`enable`, `font add`/`remove`) stay CLI-only, so a human runs them. See the
[MCP section of the README](../README.md#mcp-authoring-surface-62).

## Versioning the machine-readable contracts

Every `--json` / MCP result carries `response_version` (spec §2 rule 5: persisted contracts are
versioned, breaking changes need a migration note). One rule decides whether a change is breaking:

- **Additive and forward-compatible** — a new field with a default, or a new value in a set a
  consumer is expected to tolerate. `response_version` does **not** move. A consumer that ignores
  the field is unaffected, and a payload written before the field existed still parses, because the
  default fills it in. Declare the field forward-compatible in `CHANGELOG.md` and document it.
- **Breaking** — removing or renaming a field, changing its type, or changing the meaning of an
  existing value. `response_version` moves, and `CHANGELOG.md` carries a migration note.

`SiblingOverlap.kind` is the worked example of the first case: it defaults to `content`, so
nothing that ignores it changes behaviour and `response_version` stays at 1.

## Architecture decisions

Recorded decisions live in [`docs/adr/`](adr/) — see the [ADR index](adr/README.md). The two that
most shape the engine are [ADR-0001](adr/0001-skia-python-144-platform-baseline.md) (the skia-python
144 platform baseline and text-binding constraints) and
[ADR-0002](adr/0002-direction-inheritance-and-data-layering.md) (direction inheritance, null-as-value,
and locale data layering).

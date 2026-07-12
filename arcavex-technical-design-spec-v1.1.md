# Arcavex — Technical Design Specification

**Document version:** 1.1.0-draft
**Status:** Ready for core implementation; untrusted extension execution is deferred
**Audience:** Autonomous / semi-autonomous development agents and human engineers building the system
**Codename:** arcavex — a local-first, headless, template-driven visual composition engine with a CLI-first workflow and an optional AI-native MCP interface

---

## Revision notes — 1.1

This revision narrows the implementation model to the actual product: a local CLI-first renderer whose templates may be authored by humans or AI agents. It adds direct file mode, a developer-experience contract, one-file templates, explicit patch semantics, distinct compiled/layout document states, deterministic rerun metadata, versioned template storage, and a concrete composition root. It defers hostile Python-extension isolation and removes the implication that local extension validation is a security sandbox.

## How to use this document

This specification is the implementation contract for Arcavex. It is optimized for a small local tool that is used directly from the command line and may be driven by an AI agent. It is not a hosted platform specification.

1. Read **§1 (Vision)**, **§6.3 (Developer experience contract)**, and **§12 (Locked Decisions)** first.
2. Phases in **§11 (Delivery Plan)** are sequential gates. A phase is not complete until its user-visible workflow works, not merely its internal packages.
3. When a detail is ambiguous, resolve it in favor of, in order: **least-surprising authoring experience > deterministic behavior > stable IR > boundary discipline > feature breadth**.
4. A simple render must not require projects, manifests, extension knowledge, or configuration. Advanced structure is introduced only when the use case needs it.
5. All persisted contracts are versioned. Breaking changes require a migration note; internal implementation classes that are not persisted or exposed do not need ceremonial versioning.
6. Security requirements in this document protect the local process from malformed assets and runaway work. Python extensions are trusted local code in v1; Arcavex does not claim to sandbox hostile Python.

## 1. Vision & Product Definition

### 1.1 What Arcavex is

Arcavex is a **local-first, headless, deterministic, template-driven rendering engine** for static visual compositions: posters, social graphics, flyers, event branding, quote cards, and campaign assets. It is a programmable design backend rather than an interactive editor.

Its shortest useful workflow is deliberately small:

```bash
arcavex render poster/template.yaml --data event.yaml --format story -o poster.png
```

A template can render into multiple aspect ratios, physical formats, and locales, including mixed-script Farsi and English output. Projects, provenance, batch rendering, and versioned libraries are available when repeated production work needs them; they are not prerequisites for a one-off render.

Arcavex is **AI-authorable by design**. The primary AI use case is creating and revising templates and data, then using diagnostics, layout inspection, and rendered previews to correct them. MCP exposes the same service operations as the CLI, but the CLI remains complete and usable without MCP.

### 1.2 Operating assumptions

- Arcavex runs on a user's machine as a CLI process or local stdio MCP server.
- There is no required daemon, web service, account system, database, or network connection.
- Template files and project files are ordinary local files suitable for Git.
- AI agents are expected to author YAML templates and patch operations. They are not expected to generate Python extensions for ordinary design work.
- Built-in and explicitly enabled local Python extensions are trusted code. Isolation of hostile extension code is outside v1.
- Malformed or unexpectedly large media files are still treated as untrusted input and receive decode/resource guards.

### 1.3 What Arcavex is not

- Not an interactive editor, canvas UI, or web application.
- Not a hosted multi-user rendering service or plugin marketplace.
- Not a web-page renderer; there is no HTML/CSS engine.
- Not a video or animation engine in v1.
- Not a prepress/CMYK system in v1. PDF export is raster-embedded RGB.
- Not a secure execution environment for hostile Python plugins.

### 1.4 Personas

| Persona | Primary task | Primary surface |
|---|---|---|
| **Template developer** | Authors templates, schemas, style packs, and format variants | CLI, YAML, preview watch mode |
| **AI template author** | Creates or patches templates, inspects errors and geometry, previews, and iterates | MCP or CLI with JSON output |
| **Automation user** | Supplies data and renders one or many assets | CLI, Python API |
| **Engine developer** | Adds renderer, layout, effect, exporter, or decoder capabilities | Python code, SDK, tests |

### 1.5 Design tenets

1. **The simple path is first-class.** A template path plus data path is enough to render.
2. **Templates are data, not code.** Logic is limited to a constrained expression language and registered deterministic functions.
3. **The IR is the rendering contract.** Authoring formats compile into explicit typed documents before rendering.
4. **Determinism is a feature.** Stable inputs, engine version, platform, assets, fonts, and seed produce stable output.
5. **Progressive disclosure.** One-file templates are valid; larger templates may split schema, formats, locales, and preview data into separate files.
6. **One service layer, multiple shells.** CLI, MCP, and Python call the same application facade.
7. **Diagnostics are part of the authoring API.** Errors must identify source, location, cause, and likely correction.
8. **Fast feedback beats architectural ceremony.** Preview, validation, and layout inspection must remain cheap and direct.
9. **Contracts exist at real variation points.** Microkernel boundaries must reduce coupling, not force every built-in into operationally separate packaging.
10. **AI uses the same authoring model as humans.** No hidden template syntax or privileged mutation path exists only for agents.

## 2. System Overview

### 2.1 Layer architecture

```
┌────────────────────────────────────────────────────────────────┐
│ CLIENTS / SHELLS                                               │
│   cli (typer)              mcp_server (stdio, FastMCP)         │
├────────────────────────────────────────────────────────────────┤
│ SERVICE API / FACADE       kernel.api — the ONE front door     │
├────────────────────────────────────────────────────────────────┤
│ KERNEL (small, stable, boring)                                 │
│   ir/            domain model: versioned scene schema          │
│   contracts/     SPI: Effect, Exporter, MaskGenerator, …       │
│   registry/      typed lookup + lifecycle + capabilities       │
│   pipeline/      compile → layout → render → export            │
│   events/        hooks: pre_compile, post_layout, pre_export   │
│   diagnostics/   structured error model                        │
├────────────────────────────────────────────────────────────────┤
│ PLUGGABLE IMPLEMENTATIONS / BUILTINS                           │
│   builtin/   effects-core, shapes-core, masks-core,            │
│              export-raster, export-pdf, layout-anchors,        │
│              template-fns-core                                 │
│   user/      $ARCAVEX_HOME/extensions/** (AI/human authored)   │
├────────────────────────────────────────────────────────────────┤
│ PLATFORM / HOST                                                │
│   skia-python (SkParagraph, RuntimeEffect, ImageFilter),       │
│   filesystem, local process and resource-limit primitives      │
└────────────────────────────────────────────────────────────────┘
```

**Dependency rule (enforced in CI via import-linter):** dependencies point *inward only*. Clients import `kernel.api`. Extensions import `kernel.contracts` + `kernel.ir` + `arcavex.sdk`. The kernel imports **nothing** from clients or extensions. Extensions never import each other.

### 2.2 API vs SPI

The kernel exposes two interfaces facing opposite directions:

- **API** (faces up, toward clients): use-case functions — `render_project()`, `create_project()`, `inspect_layout()`. Stable, semver'd.
- **SPI** (faces down, toward extensions): abstract contracts — "an Effect implements `apply()` and `bounds_expansion()`". Stable, semver'd, evolved by versioned addition only.

### 2.3 Data flow and document states

The pipeline uses distinct immutable document states. Calling all of them `IR Document` is prohibited because it hides whether layout has occurred.

```text
template source + data + style + format + locale
        │ compiler
        ▼
CompiledDocument
  - expressions resolved
  - style/format/locale patches applied
  - constraints still symbolic
        │ layout solver
        ▼
LayoutDocument
  - every node has resolved bounds and absolute transform
  - overflow and measurement diagnostics attached
        │ renderer backend
        ▼
Surface
        │ exporter
        ▼
PNG / JPEG / WebP / PDF
```

`RendererBackend` accepts only `LayoutDocument`. Layout never mutates a `CompiledDocument` in place. A project render additionally writes a run manifest; direct file-mode rendering does not create a permanent run unless `--record` is requested.

## 3. Kernel Specification

The kernel is deliberately small and policy-focused, but v1 has no artificial line-count target. Size is reviewed by responsibility and dependency direction, not by moving necessary behavior into awkward packages. Any `if style == "pop-art"`-shaped branch in kernel code is still a design defect: style-specific behavior belongs behind a component contract.

### 3.1 IR — the domain model

Package: `arcavex.kernel.ir`. **Zero internal dependencies** — it imports only the standard library and pydantic. Everything else in the system depends on it; it depends on nothing.

#### 3.1.1 Schema and state types (pydantic v2 models)

```text
CompiledDocument
  ir_version: "1.0"
  canvas: {width: Dim, height: Dim, dpi: int, bleed: Insets?}
  color_policy: {working_space: "srgb", premultiplied: true, blend_space: "srgb"}
  seed: int
  fonts: [FontRef]
  root: CompiledGroup

CompiledNode (base)
  id: str
  type: group|text|image|shape|path
  transform: {translate?, rotate?, scale?, flip?, origin?}
  constraints: Constraints
  style: Style
  effects: [EffectSpec]
  mask: MaskSpec?
  visible: bool
  z: int

LayoutDocument
  source: CompiledDocumentRef
  canvas: ResolvedCanvas
  root: LayoutGroup

LayoutNode
  source_node_id: str
  bounds: Rect
  absolute_transform: Matrix3
  paint_bounds: Rect              # layout bounds expanded for effects
  overflow: OverflowState
  resolved_content: ResolvedText|ResolvedImage|ResolvedPath|...
  children: [LayoutNode]?

EffectSpec: {name: str, category: geometry|color|raster|composite, params: {…}}
AssetRef: {hash: "sha256:…", role: image|texture|svg, meta: {…}}
```

The compiler owns `CompiledDocument`; the layout solver owns `LayoutDocument`. Neither type has optional fields that silently mean “this stage has not run yet.” Node IDs remain stable across both states and are the addressing mechanism for patches, diagnostics, debug overlays, and layout inspection.

#### 3.1.2 Units and coordinates

- All authored dimensions are **physical units**: `mm`, `pt`, `px`, `%` (of parent). The compiler resolves everything to `pt`; the renderer maps pt → device pixels via `dpi` at render time. Raw-pixel-only thinking is prohibited: print formats (A4 + bleed) must be first-class from day one.
- `Insets`, `Dim`, and unit arithmetic live in `ir.units`. Property-based tests required (round-trip, associativity of conversions).

#### 3.1.3 Color policy

- Working space: **sRGB, premultiplied alpha**, blending in sRGB for v1. The policy is a *document field*, not a hardcode, so wide-gamut/linear blending later is a parameter change, not a rewrite.
- Colors parse from hex/rgba/named; stored normalized. Output surfaces are tagged sRGB.

#### 3.1.4 Versioning and validation

- `ir_version` versions the persisted `CompiledDocument` schema. `LayoutDocument` is an internal cache/result format in v1 and is not promised as a long-term persistence contract.
- Structural validation uses pydantic; semantic validation checks IDs, references, registered components, constraints, expression outputs, and effect parameters.
- Compilation and layout diagnostics are accumulated and returned together when safe to do so. A stage does not continue when its required invariants are missing.
- Canonical hashing uses normalized UTF-8 NFC strings, normalized units in points, sorted mapping keys, stable list order, normalized numeric representation, and no absolute filesystem paths. The canonical serializer is shared by template versions, manifests, and cache keys.
- Unknown major schema versions fail with a diagnostic. Minor additive fields may be ignored only where explicitly declared forward-compatible.

### 3.2 Contracts (SPI)

Package: `arcavex.kernel.contracts`. One abstract contract exists per demonstrated **axis of variation**. v1 begins with eight; adding another public contract requires an ADR tied to a concrete implementation need:

```python
class Effect(ABC):
    kind: ClassVar[EffectKind]            # GEOMETRY | COLOR | RASTER | COMPOSITE
    param_schema: ClassVar[type[BaseModel]]
    def bounds_expansion(self, params) -> Insets: ...   # MANDATORY, even if zero
    def apply(self, ctx: EffectContext) -> EffectResult: ...

class MaskGenerator(ABC):
    name: ClassVar[str]
    param_schema: ClassVar[type[BaseModel]]
    def build(self, params, bounds: Rect) -> Path2D: ...

class ShapeGenerator(ABC):                # starburst, speech_bubble, qr_code, …
    name: ClassVar[str]
    param_schema: ClassVar[type[BaseModel]]
    def build(self, params, bounds: Rect) -> Path2D: ...

class Exporter(ABC):
    format: ClassVar[str]                 # "png", "pdf", …
    def export(self, surface, target: Path, opts: ExportOptions) -> ExportReport: ...

class LayoutSolver(ABC):
    name: ClassVar[str]
    def solve(self, doc: CompiledDocument, measure: MeasureFn) -> LayoutDocument: ...

class TemplateFunction(ABC):              # pure fns callable from expressions
    name: ClassVar[str]
    def call(self, *args) -> Value: ...   # no I/O, no side effects, deterministic

class RendererBackend(ABC):
    name: ClassVar[str]
    def render(self, doc: LayoutDocument, opts: RenderOptions) -> Surface: ...

class AssetDecoder(ABC):
    media_types: ClassVar[tuple[str, ...]]
    def decode(self, blob: bytes, guards: DecodeGuards) -> DecodedAsset: ...
```

**EffectContext by category** (this is what makes the four-category split real):

| Category | Receives | Produces | Notes |
|---|---|---|---|
| `GEOMETRY` | node `Path2D`, params, seeded RNG | modified `Path2D` | runs **pre-raster**, changes shape |
| `COLOR` | params | `ColorTransform` (matrix/LUT) | consecutive color effects are **fused** into one LUT by the renderer |
| `RASTER` | input surface, params, seeded RNG | output surface | must declare bounds expansion; may allocate from surface pool only |
| `COMPOSITE` | element surface **+ backdrop accessor**, params | composited surface | shadows, glow, blend-with-backdrop |

Determinism rule for effects: any randomness must come from `ctx.rng`, seeded as `hash(document.seed, node.id, effect_index)`. Validation flags direct use of `random`, wall-clock time, or undeclared filesystem input because such use breaks reproducibility; this is a determinism rule, not a hostile-code sandbox.

### 3.3 Registry, bootstrap, and local extensions

Package: `arcavex.kernel.registry`. The application composition root lives in `arcavex.bootstrap`, outside the pure kernel. It creates registries, registers built-ins, loads explicitly enabled local extensions, and constructs `kernel.api`.

- One typed registry exists per contract: effects, masks, shapes, exporters, layout solvers, template functions, backends, and decoders.
- Built-ins obey the same contracts as extensions, but they may be distributed in the Arcavex package. v1 does not require every built-in to be a separately installed Python distribution.
- User extensions are added explicitly with `arcavex ext add <path>`. A custom local directory loader reads `extension.toml`; loose extension directories are not described as Python entry points.
- Python extensions are trusted local code. Validation catches compatibility and authoring errors, not malicious behavior.
- Lifecycle: `add → validate → disabled → enable`. Disabling removes registrations on the next process start. Built-ins are enabled by default.
- An extension package may register multiple components. The manifest therefore contains a component list rather than a single `kind`/`entry` pair.

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

Component names are globally unique by kind. Duplicate names fail at bootstrap with a diagnostic naming both providers. Extension dependencies on other extensions are prohibited in v1.

### 3.4 Pipeline orchestrator

Package: `arcavex.kernel.pipeline`. Knows the **sequence**, none of the **content**:

`compile(template, data, style, format, locale) → validate → layout → render → export`

Each step resolves its implementation through the registry. The orchestrator owns: step ordering, diagnostics aggregation, surface-pool lifetime, run-manifest assembly, and cancellation/budget enforcement (wall-clock and memory budgets per job, §8.3).

### 3.5 Events / hooks

Package: `arcavex.kernel.events`.

Hooks are **observer-only in v1**. They receive immutable snapshots and may emit diagnostics, logs, and timings. They do not mutate templates, documents, or surfaces. Any behavior that changes output must use a named contract such as an effect, layout solver, or exporter.

The four stable events are:

`pre_compile(template_source)`, `post_compile(compiled_doc)`, `post_layout(layout_doc)`, `post_export(export_report)`

Handlers run in deterministic registration order. Hook failures are wrapped as diagnostics; a hook may be marked required or best-effort when registered. Because hooks do not affect rendered bytes, they are excluded from render hashes.

### 3.6 Diagnostics

Package: `arcavex.kernel.diagnostics`. The single error model crossing every boundary (API, MCP, CLI):

```json
{
  "code": "ARC-TPL-014",
  "severity": "error",                    // error | warning | info
  "message": "Variable 'speaker_name' is required by template 'event-poster' but missing",
  "source": {"file": "data/event.yaml", "keypath": "guests[1].name", "line": 12},
  "hint": "Add 'name:' under guests[1], or mark the variable optional in schema.yaml"
}
```

Code namespaces: `ARC-TPL` (template/compile), `ARC-IR` (schema/semantic), `ARC-LAY` (layout), `ARC-FX` (effects), `ARC-RND` (render), `ARC-EXP` (export), `ARC-AST` (assets), `ARC-EXT` (extensions), `ARC-PRJ` (projects). Every code gets a docs page. **No raw exception ever crosses the API facade**; unexpected exceptions are wrapped as `ARC-INT-999` with a stack reference logged, not surfaced.

Rationale (non-negotiable): located, hinted diagnostics are simultaneously the human authoring experience and the AI self-correction loop. This is the highest-leverage quality investment in the system.

### 3.7 Service API facade

Package: `arcavex.kernel.api`. CLI, MCP, and Python wrappers contain no rendering or project logic. The v1 application surface is:

```text
# environment and discovery
workspace_info() -> WorkspaceInfo
doctor() -> DoctorReport
resolve_project(path=None) -> ProjectRef | None
explain_diagnostic(code) -> DiagnosticHelp

# direct file mode — no project required
validate_template(template, data=None, format=None, locale=None) -> [Diagnostic]
render_file(template, data, format, locale=None, style=None, output=None,
            dpi=None, debug=False, record=False) -> RenderResult
render_preview(template, data, format, locale=None, style=None,
               debug=False) -> ImageResult
inspect_layout(template, data, format, locale=None, style=None) -> LayoutReport

# projects
create_project(name, template, formats, locales, from_project=None) -> ProjectInfo
list_projects(root=None) -> [ProjectInfo]
project_status(project) -> ProjectStatus
clone_project(src, dst) -> ProjectInfo
set_project_status(project, status) -> ProjectStatus
upgrade_project_template(project, target_version) -> UpgradeReport
batch_render(projects, formats=None, locales=None, jobs=None) -> BatchRunInfo

# data and assets
set_data(project, keypath, value) -> [Diagnostic]
import_data(project, yaml_text, locale=None) -> [Diagnostic]
add_asset(project_or_workspace, source, name=None, annotations=None) -> AssetRef
annotate_asset(ref, annotations) -> AssetRef

# template and style library
list_templates() -> [TemplateInfo]
inspect_template(ref) -> TemplateSchema
scaffold_template(target, name=None, split=False) -> TemplateInfo | [Diagnostic]
split_template(ref) -> TemplateInfo | [Diagnostic]
publish_template(source, name, version) -> TemplateInfo | [Diagnostic]
patch_template(ref, patch) -> TemplateInfo | [Diagnostic]
list_styles() -> [StyleInfo]
inspect_style(ref) -> StyleInfo

# project rendering and runs
render_project(project, formats=None, locales=None, dpi=None) -> RunInfo
list_runs(project) -> [RunInfo]
diff_runs(run_a, run_b) -> RunDiff
rerun(run_dir) -> RunInfo

# trusted local extensions
list_extensions() -> [ExtInfo]
scaffold_extension(kind, target, name=None) -> ExtInfo | [Diagnostic]
add_extension(path) -> ExtInfo | [Diagnostic]
validate_extension(name) -> [Diagnostic]
test_extension(name) -> ExtTestReport
enable_extension(name) -> ExtState
disable_extension(name) -> ExtState
```

“Active project” is not global application state. Clients pass their current path or explicit `--project` value to `resolve_project`; the facade performs upward discovery for `project.yaml`. This keeps concurrent terminals and AI processes independent.

## 4. Subsystem Specifications

Everything in this section is implemented as kernel-adjacent services or builtin extensions — never as kernel special cases.

### 4.1 Template system

Location: `arcavex/services/template/` (loader, expressions, styles, formats, compiler, diagnostics). Authoring YAML is parsed with `ruamel.yaml` so line/column locations and comments survive validation and AI-applied patches; canonical hashing uses a separate normalized serializer.

#### 4.1.1 Authoring format and progressive disclosure

YAML is primary; JSON and TOML are accepted where the same data model can be represented. A template may begin as one file:

```yaml
version: 0.1.0
variables:
  title: {type: string, required: true, doc: "Main headline"}
formats:
  square: {canvas: {width: 1080px, height: 1080px, dpi: 96}}
preview_data:
  title: "Example event"
root:
  type: group
  id: root
  children: [...]
```

For larger templates the same sections may be split without changing semantics:

```text
event-poster/
├── template.yaml        # root node tree and template metadata
├── schema.yaml          # optional split of `variables`
├── formats.yaml         # optional split of `formats`
├── locales.yaml         # optional split of `locales`
└── preview-data.yaml    # optional split of `preview_data`
```

Rules:

- `template.yaml` is always required.
- A variable declaration is required for every externally supplied variable reference. Literal-only templates need no schema.
- Inline and split definitions cannot define the same key; duplication is an error rather than a precedence puzzle.
- Every authored node requires a stable human-readable `id`. A `repeat` node also declares a stable `key` expression; expanded IDs become `<authored-id>[<key>]`. Index-derived keys are allowed only with an explicit `key: "{{ loop.index }}"` and produce a stability warning because reordering changes IDs.
- `arcavex template new` creates a minimal valid one-file template. `arcavex template split` expands it into the directory form when needed.
- `arcavex template inspect --json` returns variable types, formats, locales, node IDs, registered components, and example data so an AI does not need to infer the contract from raw source.

#### 4.1.2 Expression language

A constrained, deterministic evaluator embedded in string values via `{{ … }}` and in structural constructs (`if:`, `repeat:`). This is the only expression delimiter; single braces are never expressions. **Explicitly not Turing-complete.**

- Supports: literals; variable paths (`{{ event.title }}`, `{{ asset.facing }}`); arithmetic/comparison/boolean ops; ternary; string ops (concat, upper, slice, format); list ops (`len`, index, `repeat over:`); calls into registered `TemplateFunction`s (e.g. `locale_digits(time, 'fa')`, `contrast_color(bg)`).
- Forbidden by construction: I/O, imports, attribute access on host objects, recursion, unbounded loops (iteration cap 1,000; evaluation budget 10ms/expression).
- Evaluator implemented over a hand-rolled AST (no `eval`), property-tested for determinism and budget enforcement.
- If a scalar is exactly `{{ expression }}`, the expression keeps its native type. Interpolation inside surrounding text converts the value to a locale-aware string.
- A literal `{{` is written as `\{{`; the loader unescapes it after expression scanning.
- Missing variables are errors unless accessed through an explicit optional/default operation. Truthiness is defined only for booleans, null, numbers, strings, and collections; host-language object truthiness is not exposed.
- `repeat` requires a stable `key:` expression for object collections so expanded node IDs and diagnostics remain stable.

Structural constructs (compiler-level, not string-level):

```yaml
- repeat: "{{ guests }}"                # loop → N sibling nodes
  as: guest
  key: "{{ guest.id }}"                  # expanded IDs remain stable
  node:
    type: group
    children: [...]
- if: "{{ qr_link is not none }}"           # conditional inclusion
  node: {type: shape, generator: qr_code, params: {data: "{{ qr_link }}"}}
```

#### 4.1.3 Style packs

A style pack is a named, versioned YAML bundle in the global library: palettes, font stacks, effect presets (named parameter sets), shape presets, and per-role defaults (`heading`, `body`, `accent`).

```yaml
# styles/pop-art.yaml
version: 0.3.0
palettes: {warhol_1: ["#FF3EA5", "#FFD600", "#00C2FF", "#1A1A1A"], …}
fonts: {display: [Archivo Black, Estedad Black], body: [Inter, Vazirmatn]}
effect_presets:
  halftone: {name: halftone-cmyk, params: {pitch: 6pt, angles: [15, 75, 0, 45]}}
  outline:  {name: sobel-outline, params: {weight: 2.5pt, threshold: 0.4}}
```

Templates opt in via `style: pop-art@0.3`; nodes reference presets (`effect_preset: halftone`); projects may override style parameters. Resolution order (last wins): style defaults → template values → format override → locale override → project override.

#### 4.1.4 Formats, locales, and patch semantics

Formats define named canvas targets and optional template patch operations. Locales define direction, digit policy, font-stack overrides, and optional data overlays.

Template structure is not modified by generic deep merge. Structural overrides use a small path-addressed patch language designed around stable node IDs:

```yaml
patch:
  - set: nodes.title.constraints.size.w
    value: 70%
  - set: nodes.title.style.font_size
    value: 42pt
  - remove: nodes.qr
  - insert_after: nodes.title
    node: {id: subtitle, type: text, ...}
```

v1 operations are exactly `set`, `remove`, `insert_before`, and `insert_after`. Paths address nodes by ID, not array index. An unknown path is an error. Operations are applied in file order and recorded in diagnostics and provenance.

Data overlays use separately defined merge semantics: mappings merge recursively, scalar values replace, lists replace as a whole, and an explicit `!delete` marker removes a key. `null` remains a valid data value and therefore does not mean deletion.

Resolution order is:

`style defaults → template values → format patch → locale patch → project patch`

Each layer is inspectable with `arcavex template inspect --resolved ...`, which reports where every final value came from.

#### 4.1.5 Compiler

`(template, data, style, format, locale) → CompiledDocument`.

Stages: load source → combine inline/split files → validate variable declarations → resolve style → apply format patch → apply locale data and patch → apply project patch → evaluate expressions and structural constructs → normalize units/colors/fonts/assets → emit `CompiledDocument` → semantic validation.

Compilation is all-or-nothing for one `(format, locale)` target. Batch and project rendering continue with other targets after a target-specific failure. Diagnostics preserve both the original authoring location and the resolved patch layer that introduced a value.

### 4.2 Layout engine

Location: `extensions/builtin/layout-anchors/`, implementing `LayoutSolver`.

v1 is an **anchor resolver**, not a general-purpose linear constraint solver. This keeps authoring understandable and diagnostics actionable.

- Nodes use logical `start`/`end` directions, resolved through the enclosing group's `direction`.
- Position may be resolved from parent or named sibling anchors. Size modes are `fixed`, `fill`, `fit_content`, and `aspect(w:h)` with optional `min`/`max` bounds.
- Groups may use absolute layout, `hstack`, or `vstack`; stacks define gap, main-axis alignment, cross-axis alignment, padding, and optional wrapping only if explicitly enabled.
- Each node must resolve exactly one horizontal position, one vertical position, width, and height. Under-constrained or contradictory declarations are errors. There is no undocumented precedence between conflicting anchors.
- Text measurement may iterate up to eight times for fit policies. Failure to converge produces a located diagnostic with measured values.
- Rotations use an explicit transform origin and contribute their post-transform AABB to sibling/layout inspection.
- Layout bounds exclude visual effect expansion. `paint_bounds` is computed afterward from effect declarations.
- Final geometry is normalized to 1/1024 point before hashing and rendering to avoid floating-point drift.
- Output is a new immutable `LayoutDocument`; the input `CompiledDocument` is never mutated.

Fit policies on text are `shrink_to_fit(min_size)`, `truncate(ellipsis)`, `wrap`, and `overflow(clip|allow|error)`. `inspect_layout` exposes resolved bounds, free regions, overlaps, overflow, and the anchor chain used to derive each node.

### 4.3 Text stack

Location: `arcavex/services/text/`.

- **Single source of truth: SkParagraph** (via skia-python). It performs shaping (HarfBuzz), BiDi, per-run font fallback, and metrics. No second shaper anywhere in the codebase — mixed metrics is a banned pattern.
- **Fonts are bundled and pinned.** The font database builds once from `$ARCAVEX_HOME/fonts/` + template-declared fonts; system fonts are never consulted (determinism). Required v1 families: a Latin workhorse (Inter), a Persian-capable pairing (Vazirmatn; display: Estedad or Lalezar). Fallback chains are declared per style role and resolved per-run so Latin-inside-Farsi lines shape correctly.
- **Digits & locale details** are handled in the variable layer (template function `locale_digits`), not in the shaper — explicit, testable, reversible.
- The v1 text schema explicitly covers font family/fallback, size, weight, slant, letter spacing, line height, alignment, direction, language tag, maximum lines, and ellipsis. Unsupported typography fields fail validation instead of being silently ignored.
- Text input is normalized to Unicode NFC. Missing glyphs identify the code points and attempted font chain in diagnostics.
- Bidi/RTL acceptance artifact: the IPEN bilingual poster (Farsi headline, mixed-direction credit lines, RTL group layout) is golden case #2 for the entire engine.

### 4.4 Effect system

Location: `extensions/builtin/effects-core/` plus trusted local extensions.

Authors specify an **ordered effect list** on each node. v1 does not expose arbitrary graph branching in template syntax. The renderer compiles that list into an internal category-aware execution plan:

`geometry → fused color transforms → ordered raster passes → composite passes`

This resolves the previous ambiguity between “effect list” and “typed DAG”: the authoring model is linear; the backend may build an internal graph for allocation and fusion.

- Every effect declares one category and a typed parameter schema.
- `bounds_expansion()` is mandatory and contributes to `paint_bounds`, not layout bounds.
- Randomness comes only from the seeded effect context.
- Color effects may be fused when doing so is semantically identical; verbose/debug output may report the resulting execution plan for engine debugging.
- Composite effects receive a read-only backdrop snapshot representing content already painted below the node in stable z-order.
- A geometry effect applies only to nodes that can expose a path. Applying one to an unsupported node is a validation error unless the backend explicitly defines a deterministic outline conversion.
- v1 built-ins: blur, drop-shadow, glow, duotone, threshold, grade, posterize/palette-map, grain, noise, ink-bleed, halftone, channel-offset, torn-paper, and edge-wear.

SkSL is preferred for shader effects, but ordinary template authors do not need to understand shaders or extension manifests.

### 4.5 Rendering

Location: `extensions/builtin/backend-skia/` implementing `RendererBackend`. The backend is swappable by contract; v1 ships Skia only.

- **Traversal:** stable document order, `z` within siblings; groups may clip; masks resolve through `MaskGenerator` registry to clip paths (the diamond-grid photo treatment is `ImageNode + mask{component: diamond_grid}` — one image, parametric grid, gutters as path gaps).
- **Surface management:** pooled, budgeted allocations (A4@300dpi ≈ 35 MB RGBA per surface; a 4-deep raster chain must reuse, not accumulate). Pool lifetime = one pipeline run.
- **Determinism controls:** all randomness via seeded RNG tree (§3.2); no wall-clock, no HashMap-iteration-order dependencies (Python dicts are ordered — rely on explicit ordering anyway); parallel batch rendering must be output-identical to serial (jobs are independent; no intra-job parallelism in v1).
- **GPU:** out of scope v1; the contract boundary (`RendererBackend`) is the seam where a Graphite-backed or Vello backend lands later without touching anything above it.

### 4.6 Exporters

`extensions/builtin/export-raster/` (PNG, JPEG, WebP — quality/compression in `ExportOptions`) and `export-pdf/` (v1 policy: **raster-embedded RGB PDF** at target DPI with correct physical page size and bleed boxes; vector-preserving PDF and CMYK/PDF-X are explicitly future work, see §12). Exported files may contain only stable metadata: engine version, render signature, color profile, and content hash. Timestamps and run IDs live only in manifests so identical reruns can remain byte-identical.

### 4.7 Asset system

Location: `arcavex/services/assets/`.

- **Content-addressed store (CAS):** assets ingest by sha256 into `objects/ab/cdef…`; references in compiled documents are hashes, never paths. Authors may still use ordinary template-relative or project-relative paths. The compiler ingests them automatically, so CAS mechanics do not appear in the simple workflow.
- **Sidecar metadata** per object: mime, dimensions, and **annotations** — `facing: left|right`, `focal_point: [0.62, 0.30]`, free-form tags. Annotations are written once (by humans, or by an AI via `annotate_asset` after *looking* at the image) and consumed by template expressions (`flip: "{{ 'horizontal' if asset.facing == 'right' else 'none' }}"`). **Render-time image analysis is prohibited** — perception happens at ingest time as stored data; renders stay deterministic.
- **Decode guards** (every decoder enforces): max decoded pixels (default 100 MP), max source bytes, format allowlist, SVG complexity caps. A decoder that decompresses first and checks second is a security bug.
- **Derived cache:** downscaled variants keyed by `(hash, params)` under an LRU byte budget, so a 40 MP photo placed into a 400 px slot never decodes at full size twice.

---

## 5. Project & Workspace Model

Three trees with independent lifecycles: the **engine** (installed package), the **global library** (a git-managed design system), and **projects** (one directory per campaign).

### 5.1 Global library — `$ARCAVEX_HOME` (default `~/.arcavex/`)

```text
~/.arcavex/
├── config.toml
├── templates/
│   └── <name>/
│       ├── <version>/...          # immutable versioned template directories
│       └── index.toml             # available versions and optional default alias
├── styles/<name>/<version>.yaml
├── fonts/
├── assets/objects/...
├── cache/                         # disposable
└── extensions/
    ├── sources/<name>/...
    └── state.toml                 # added/enabled state
```

The library is optional in direct file mode. A template reference may be either a filesystem path or `name@version`. Bare `name` is allowed only when the library defines an explicit default version; Arcavex never silently selects “latest” during a recorded project render.

### 5.2 Project layout

```
ipen-june-meetup/
├── project.yaml                 # manifest — the tracking unit
├── data/
│   ├── event.yaml               # base data
│   ├── event.fa.yaml            # locale data overlay (§4.1.4)
│   └── event.en.yaml
├── assets/                      # project-local sources (ingested to CAS on use)
├── overrides/
│   └── event-poster.patch.yaml  # patches, never forks (§5.4)
└── outputs/
    └── 2026-07-10T14-22-03Z_a1b2c3/
        ├── manifest.json        # provenance (§5.3)
        ├── poster.a4.fa.png
        └── poster.story.en.png
```

**`project.yaml`:**

```yaml
name: ipen-june-meetup
template: event-poster@1.2.0      # pinned semver from global library
style: null                       # or pop-art@0.3
locales: [fa, en]
formats: [a4, story, square]
data: data/event.yaml
status: draft                     # draft | review | approved | published
tags: [ipen, 2026, meetup]
```

### 5.3 Provenance — run manifests

Projects and direct renders executed with `--record` write a run directory containing `manifest.json`. The manifest records engine version, platform, IR version, canonical template/style/data hashes, resolved data snapshot, asset and font hashes, seed, options, diagnostics, timings, and output hashes.

- Exported image/PDF files do not embed timestamps or run IDs.
- `rerun` uses the original resolved snapshot and stable render metadata. It creates a new surrounding run directory and a reproduction report, but the rendered output bytes must match on the same engine version and platform.
- When the original engine version is unavailable, Arcavex refuses to claim exact reproduction and may perform an explicitly labeled compatibility render.
- Direct unrecorded renders optimize iteration speed and leave only the requested output plus transient cache entries.
- `diff` reports pixel/perceptual differences and separately reports template, data, asset, font, engine, and option changes.

### 5.4 Two enforced rules

1. **Project overrides are patch operations, not template forks.** Patches address stable node IDs and use the operation model in §4.1.4. Copying a library template into a project is allowed only through an explicit `arcavex template detach` command that warns the user that version upgrades are no longer available.
2. **Files are canonical; indexes and caches are disposable.** `project.yaml`, template sources, data, and manifests are the source of truth. A SQLite index may accelerate discovery later but is never authoritative.

### 5.5 Template versioning

Library templates are stored immutably under `templates/<name>/<version>/`. Projects pin exact versions. Creating or patching a published version produces a new version; it never edits the old directory in place.

`arcavex project upgrade --to <version>` performs:

1. compile old and target versions over current project data;
2. report patch paths that no longer resolve;
3. render comparable previews;
4. show structural and perceptual diffs;
5. update the pin only after explicit acceptance.

A working template path outside the library may use `version: 0.0.0-dev` and be edited freely. Version immutability begins when it is published into the local library.

## 6. Clients

Both clients parse transport-specific input, call `kernel.api`, and format results. Project discovery, rendering, compilation, patching, and project behavior remain in the service layer; clients own only CLI/MCP parsing and presentation.

### 6.1 CLI (`arcavex`, built on Typer)

#### 6.1.1 Direct file mode

```bash
arcavex validate poster/template.yaml --data event.yaml --format story
arcavex preview poster/template.yaml --data event.yaml --format story --watch
arcavex render poster/template.yaml --data event.yaml --format story -o out.png
arcavex layout inspect poster/template.yaml --data event.yaml --format story
```

No workspace initialization or project is required. Relative assets resolve from the template directory first and the data file directory second; ambiguous matches are errors.

#### 6.1.2 Project mode

```bash
arcavex project new ipen-june --template event-poster@1.2.0
cd ipen-june
arcavex status
arcavex preview --format story --locale fa --watch
arcavex render
arcavex batch ../campaigns/* --jobs 4
arcavex project upgrade --to 1.3.0
arcavex rerun outputs/<run>
arcavex diff outputs/<run-a> outputs/<run-b>
```

The CLI discovers `project.yaml` by walking upward from the current directory. `--project <path>` overrides discovery. There is no persistent `arcavex open` state.

#### 6.1.3 Authoring and diagnostics

```bash
arcavex template new event-poster
arcavex template check ./event-poster
arcavex template inspect ./event-poster --json
arcavex template split ./event-poster
arcavex template publish ./event-poster --name event-poster --version 1.0.0
arcavex explain ARC-LAY-031
arcavex doctor
```

Every command supports `--json`, `--no-color`, and `--quiet`. Machine-readable output uses versioned response models rather than parsing human console text.

Exit codes:

- `0`: success, including warnings
- `1`: validation or authoring error
- `2`: invalid CLI usage
- `3`: missing dependency, font, template, asset, or extension
- `4`: resource budget or cancellation
- `5`: internal failure, accompanied by `ARC-INT-999`

`preview --watch` writes to a stable temporary preview location and does not create recorded runs. It prints changed dependencies, compile time, render time, and the first actionable diagnostic. A successful save-to-preview loop should require one command and no manual cache management.

### 6.2 MCP server (`arcavex mcp serve`)

Transport is local stdio. Tool inputs and outputs mirror the service API and use the same pydantic models. MCP is optional; no engine capability exists only through MCP.

The default v1 tool set focuses on template authoring:

```text
arcavex_template_list / _inspect / _validate / _patch
arcavex_project_create / _list / _status / _clone
arcavex_data_set / _import
arcavex_asset_add / _annotate
arcavex_render_preview
arcavex_layout_inspect
arcavex_render
arcavex_run_list / _diff / _rerun
arcavex_diagnostic_explain
```

`arcavex_render_preview` returns image content directly. With `debug=true`, it overlays node IDs, bounds, baselines, anchors, and overflow. `arcavex_layout_inspect` returns geometry and anchor derivations. Visual contrast analysis that depends on image pixels is a post-render inspection, not a layout claim.

MCP tools for writing or enabling Python extensions are deferred beyond v1. An AI may author templates, styles, patch files, and data through the supported authoring contracts without receiving a code-execution pathway.

### 6.3 Developer experience contract

DX requirements are release criteria, not documentation aspirations.

#### Human template workflow

1. `arcavex template new` generates a renderable example.
2. `arcavex preview --watch` starts the loop.
3. Saving any dependent template, data, style, or asset file triggers one incremental rebuild.
4. Errors retain the previous successful preview and report the exact source location plus correction hint.
5. `arcavex layout inspect` explains geometry numerically when the preview alone is insufficient.

#### AI template workflow

1. Inspect the template schema and available component catalogs as JSON.
2. Apply path-addressed patches using stable node IDs.
3. Validate before rendering when possible.
4. Request a debug preview and layout report.
5. Correct from structured diagnostics; never scrape Rich console output.

#### Progressive disclosure rules

- One-file templates, direct render mode, and sensible defaults are always supported.
- Project manifests, libraries, version pins, styles, and extensions appear only when invoked.
- No command requires knowledge of IR classes.
- No ordinary template requires Python.
- No author must manually calculate a CAS hash or register a relative asset.
- A command that can infer an unambiguous value should do so and report the inference in verbose/JSON output.
- Ambiguity produces a diagnostic; Arcavex does not silently choose an asset, format, locale, or template version.
- A format or locale may be inferred only when exactly one valid choice exists. The inference is included in JSON/verbose output.
- Runtime configuration precedence is `CLI flag → ARCAVEX_* environment variable → project.yaml → ~/.arcavex/config.toml → built-in default`. Template/style/format/locale value resolution remains the separate order defined in §4.1.4.
- Default output naming is deterministic and shown before rendering: `<template>.<format>[.<locale>].<ext>`. An explicit `-o` always wins.

#### Documentation and examples

The repository ships three copyable examples matching the golden cases. Every public template field and diagnostic code has one concise reference entry. Examples are tested in CI so documentation cannot drift from the parser.

## 7. Trusted Local Extension Development

Extensions are an engine-development mechanism, not the normal template-authoring mechanism.

### 7.1 The SDK — `arcavex.sdk`

The SDK re-exports stable contracts, parameter-schema helpers, deterministic RNG, path/surface utilities, registration helpers, and a GoldenHarness. Extensions may import only the SDK plus explicitly documented IR value types.

### 7.2 Workflow

```text
scaffold → implement → validate → golden test → add → enable
```

```bash
arcavex ext scaffold effect paper-texture
arcavex ext validate ./paper-texture
arcavex ext test ./paper-texture
arcavex ext add ./paper-texture
arcavex ext enable paper-texture
```

Validation checks manifest shape, component names, engine/IR compatibility, parameter schemas, imports, deterministic API usage, and shader compilation. Golden tests verify output and effect bounds.

### 7.3 Trust boundary

Python extensions execute with the permissions of the Arcavex process and are therefore **trusted local code**. AST checks and subprocess tests improve reliability but are not described as a security sandbox. Extensions obtained from an AI or third party must be reviewed like any other local Python dependency before enabling.

The render path itself remains network-free by design, but v1 does not attempt to defend against a deliberately malicious enabled Python extension.

### 7.4 Deferred untrusted runtime

A WASM or OS-isolated worker runtime may be added after v1 if real third-party extension distribution requires it. This is not a prerequisite for AI-authored templates, local CLI use, or the initial extension SDK.

## 8. Non-Functional Requirements

### 8.1 Determinism (definition & enforcement)

**Definition:** identical output bytes given the same *engine version + platform (OS/arch) + pinned assets/fonts + seed + options*. Cross-platform bit-identity is a non-goal; cross-platform *perceptual* identity is enforced by golden thresholds.

Enforcement: seeded RNG tree only; bundled fonts only; no wall-clock inputs; stable traversal/order; batch parallelism must be output-equal to serial; run manifests capture every input by hash.

### 8.2 Performance targets (p95, warm process, reference: 8-core x86-64 or Apple-silicon laptop)

| Operation | Target |
|---|---|
| Template compile (typical event poster) | ≤ 50 ms |
| Render 1080×1350, ≤ 3 raster effects | ≤ 1.5 s |
| Render A4 @ 300 dpi, 4-deep effect chain | ≤ 6 s |
| Peak RSS per render job (A4@300, pooled) | ≤ 1.5 GB |
| Batch scaling | ~linear in `min(cores, jobs)` |
| CLI cold start to first render begin | ≤ 400 ms |

ARM64 (incl. Raspberry-Pi-class) is a supported build target with relaxed (2×) targets, not a primary optimization goal.

### 8.3 Local safety and resource limits

Arcavex is a local tool, not a multi-tenant service. v1 safety focuses on malformed inputs, accidental runaway work, and predictable machine usage:

- safe YAML parsing with no object construction;
- path and symlink traversal checks for template/project-relative files;
- image, SVG, and font size/complexity guards before expensive decode or shaping;
- repeat-count, expression-depth, and evaluation-time budgets;
- per-render wall-clock, decoded-pixel, surface-memory, and output-dimension budgets;
- atomic writes through temporary files followed by rename;
- immutable completed run directories;
- clean cancellation without publishing partial outputs;
- trusted-local-code warning for enabled Python extensions;
- atomic CAS insertion by hash, lock-protected template publication and extension-state updates, and unique run directories for concurrent renders;
- no shared mutable “active project” state between processes. Source files remain editor-owned; Arcavex detects changed-on-disk revisions before applying a patch and refuses to overwrite them silently.

Network access is not used by compilation or rendering. MCP uses local stdio. Hosted-service concerns such as user authentication, tenant isolation, quotas, and remote secret management are deferred because they are outside the product definition.

### 8.4 Observability

Structured logging (stdlib `logging`, JSON handler option), one log line per pipeline stage with run_id correlation; `--verbose` traces registry resolutions; render timings recorded into run manifests for regression tracking. No telemetry, no phoning home.

### 8.5 Testing strategy

| Layer | Method |
|---|---|
| Units, expressions, unit-conversions | pytest + **property-based** (hypothesis) for evaluator & units |
| Layout | **JSON bounds snapshots** (cheap, cross-platform deterministic) |
| Rendering | **Golden images**, perceptual diff (dssim ≤ 0.003), per-platform golden sets |
| Effects | GoldenHarness fixtures incl. bounds-expansion honesty check (tight vs padded render diff) |
| Extensions | manifest, compatibility, deterministic-API lint, crash containment during tests, and golden fixtures |
| End-to-end | golden case #1: hardcoded hello-poster; **#2: IPEN bilingual poster** (fa/en × 3 formats — exercises shaping, BiDi, RTL layout, masks, rotation); **#3: pop-art Warhol grid** (shaders, loops, style packs) |
| CLI DX | tested command transcripts for direct render, project discovery, watch mode, JSON output, and exit codes |
| Agent dogfood | scripted MCP sessions: inspect → patch → validate → preview → inspect_layout → render |
| File safety | atomic-write, interrupted-render, malformed asset, path traversal, and concurrent-read fixtures |

CI matrix: linux-x86_64 + macos-arm64 (linux-aarch64 added Phase 7). Golden updates require `make golden-update` + reviewed image diff artifacts.

---

## 9. Engineering Standards

- **Language/runtime:** Python ≥ 3.11. Core deps: `skia-python`, `pydantic v2`, `typer`, `ruamel.yaml`, `rich`, `mcp` (FastMCP). Dev: `ruff`, `mypy`, `pytest`, `hypothesis`, `import-linter`, `dssim` binding.
- **Typing:** `mypy --strict` on `kernel/`, `sdk/`, `services/`. Extensions: strict-encouraged, validated at their gate.
- **Architecture enforcement:** import-linter contracts encode §2.1's dependency rule; CI fails on violation. This is the mechanized kernel boundary.
- **Errors:** no raw exceptions across `kernel.api`; diagnostics everywhere (§3.6). No `print` outside clients.
- **Style:** ruff (line length 100), Google-style docstrings on all public API/SPI, module-level docstring stating the module's single responsibility.
- **Decisions:** ADRs in `docs/adr/NNNN-title.md` for persisted contracts, public APIs, layout semantics, or locked decisions. Internal refactors do not require ADR ceremony.
- **DX compatibility:** CLI JSON schemas, exit codes, template syntax, patch operations, and diagnostic codes are public contracts with snapshot tests.
- **Versioning:** engine semver; IR semver; each contract carries `since=` metadata. Conventional commits; changelog generated.

---

## 10. Repository Layout

```text
arcavex/
├── pyproject.toml
├── Makefile
├── docs/
│   ├── adr/
│   ├── diagnostics/
│   ├── template-reference.md
│   └── extension-guide.md
├── src/arcavex/
│   ├── bootstrap.py                 # composition root; registers built-ins/local extensions
│   ├── kernel/
│   │   ├── ir/
│   │   ├── contracts/
│   │   ├── registry/
│   │   ├── pipeline/
│   │   ├── events.py
│   │   ├── diagnostics.py
│   │   └── api.py
│   ├── services/
│   │   ├── template/
│   │   ├── layout_support/
│   │   ├── text/
│   │   ├── assets/
│   │   ├── projects/
│   │   ├── cache/
│   │   └── config/
│   ├── sdk/
│   └── clients/
│       ├── cli.py
│       └── mcp_server.py
├── extensions/builtin/
│   ├── backend-skia/
│   ├── layout-anchors/
│   ├── effects-core/
│   ├── masks-core/
│   ├── shapes-core/
│   ├── template-fns-core/
│   ├── export-raster/
│   └── export-pdf/
├── library-seed/
│   ├── templates/<name>/<version>/
│   ├── styles/<name>/<version>.yaml
│   └── fonts/
├── examples/
│   ├── hello-poster/
│   ├── ipen-bilingual/
│   └── pop-art-grid/
└── tests/
    ├── unit/
    ├── property/
    ├── layout_snapshots/
    ├── golden/
    ├── cli_sessions/
    ├── mcp_sessions/
    └── file_safety/
```

The composition root resolves the previous dependency ambiguity: the pure kernel does not import extensions, while `bootstrap.py` knows both and wires them together.

## 11. Delivery Plan (sequential gates)

**Phase -1 — Skia feasibility.** Verify skia-python installation, SkParagraph shaping/metrics, bundled-font loading, RuntimeEffect, image filters, deterministic CPU output, PDF page sizing, and ARM64 availability. *Exit:* throwaway scripts render mixed Farsi/English text and one SkSL effect on primary development platforms.

**Phase 0 — Core model and direct CLI slice.** Repository, diagnostics, canonical hashing, `CompiledDocument`/`LayoutDocument`, registries/bootstrap, provisional renderer, PNG export, and `arcavex render template.yaml --data ...`. *Exit:* hello poster renders from a one-file template with no project or config.

**Phase 1 — Authoring loop.** One-file/split template loader, variable schema, expression parser, direct validation, watch preview, JSON output, exit codes, and `doctor`. *Exit:* save-to-preview loop works under two seconds and reports seeded authoring errors with source locations.

**Phase 2 — Layout, text, and locales.** Anchor resolver, fit policies, SkParagraph, RTL/logical directions, format/locale patch operations, masks, layout inspection, and debug overlays. *Exit:* IPEN poster renders Farsi and English in square/story/A4 from one template.

**Phase 3 — Effects and styles.** Ordered effect authoring model, internal execution plan, bounds expansion, color fusion, SkSL halftone, built-in effects/shapes, and style packs. *Exit:* pop-art grid golden case passes and effect bounds tests are green.

**Phase 4 — Projects and provenance.** Project discovery, versioned local library, canonical run manifests, stable reruns, diffs, batch rendering, project patches, and upgrade previews. *Exit:* same-platform rerun is byte-identical and project upgrade detects stale patch paths.

**Phase 5 — MCP authoring surface.** Template inspection/patching, structured diagnostics, preview image content, layout inspection, project/data/asset tools, and scripted agent sessions. *Exit:* an agent creates and corrects a poster using only supported template operations.

**Phase 6 — Trusted local extension SDK.** Multi-component manifests, local directory loader, scaffold/validate/test/add/enable workflow, GoldenHarness, and extension docs. *Exit:* a reviewed local effect extension can be added and used without modifying Arcavex core.

**Phase 7 — Export and release hardening.** JPEG/WebP, raster PDF with bleed, cache budgets, atomic writes, interruption tests, performance targets, linux-aarch64 CI where feasible, packaged installation tests, and v0.1 release.

**Post-v1:** hostile-extension isolation, WASM runtime, GPU backend, vector PDF/CMYK, animation, hosted service concerns.

## 12. Locked Decisions & Open Questions

### Locked

1. **Local-first and CLI-complete.** No daemon, account, network, database, or MCP host is required to render.
2. **Two usage modes.** Direct file mode is the simple path; project mode adds repeatability and history.
3. **AI primarily authors templates, data, styles, and patches**, not executable Python extensions.
4. **Distinct pipeline states:** `CompiledDocument` and `LayoutDocument`; renderer accepts only the latter.
5. **One expression delimiter:** `{{ ... }}` everywhere.
6. **Stable node IDs** are mandatory and are used for patches, diagnostics, debug overlays, and inspection.
7. **Structural overrides use explicit path-addressed operations**, not ambiguous deep merge.
8. **Templates may be one file or split files with identical semantics.** Duplicate inline/split definitions are errors.
9. **Template library versions are immutable directories** and projects pin exact versions.
10. **One text stack:** SkParagraph for shaping and metrics; bundled fonts only for recorded deterministic renders.
11. **Layout is an understandable anchor resolver**, not an unconstrained general solver in v1.
12. **Effect authoring is an ordered list;** the renderer may compile it into an internal category-aware plan.
13. **Output bytes contain no volatile run ID or timestamp.** Provenance metadata lives in manifests.
14. **Hooks are observer-only in v1.** Output-changing behavior uses contracts.
15. **Built-ins obey contracts but need not be separately installed packages.** `bootstrap.py` is the composition root.
16. **Local Python extensions are trusted code.** Hostile-code isolation is deferred and is not implied by validation.
17. **Physical units, DPI, RTL logical directions, deterministic seeds, CAS-backed assets, and structured diagnostics remain first-class.**
18. **MCP mirrors the service API and provides no exclusive engine capability.**

### Open — decide during the marked phase

- Exact Skia/SkParagraph support matrix after Phase -1.
- SVG ingestion: Skia SVG module versus guarded rasterization at ingest, Phase 2.
- Preview cache granularity and invalidation after real watch-mode profiling, Phase 1/3.
- Hyphenation only if a concrete template requires it, Phase 3.
- Whether compatibility reruns may automatically install an older Arcavex version, Phase 4.
- GPU backend, vector PDF, CMYK/PDF-X, WASM extension runtime, and animation after v1.

## Appendix A — Illustrative IR fragment (bilingual poster excerpt)

```yaml
ir_version: "1.0"
# CompiledDocument excerpt; layout adds resolved bounds in a separate LayoutDocument
canvas: {width: 210mm, height: 297mm, dpi: 300, bleed: 3mm}
color_policy: {working_space: srgb, premultiplied: true, blend_space: srgb}
seed: 8412
root:
  type: group
  direction: rtl
  children:
    - id: tower-photo
      type: image
      asset: {hash: "sha256:9f3a…", role: image, meta: {facing: left}}
      constraints: {anchor: {top: parent.top, end: parent.end}, size: {w: 62%, h: 68%}}
      mask: {component: diamond_grid, params: {cell: 90pt, gutter: 6pt, angle: 45}}
    - id: title
      type: text
      runs: [{text: "یک فنجان تجربه", style_role: display}]
      paragraph: {align: start, direction: rtl}
      fit: {policy: shrink_to_fit, min_size: 24pt}
      constraints: {anchor: {top: parent.top+120pt, start: parent.start+40pt}, size: {w: 34%}}
      effects: [{name: drop-shadow, category: composite, params: {blur: 4pt, dy: 2pt}}]
```

## Appendix B — Glossary

**IR** — intermediate representation; the versioned, fully-resolved scene document. **SPI** — service provider interface; contracts extensions implement. **Style pack** — named bundle of palettes/fonts/effect presets. **CAS** — content-addressed store. **Run manifest** — provenance record making a render reproducible. **Golden test** — reference-image regression test with perceptual thresholds. **Disabled/enabled** — explicit local extension registration states. **Logical directions** — start/end layout vocabulary resolved by group direction (RTL-aware). **Direct mode / project mode** — one-off rendering versus tracked campaign rendering.

---

*End of specification. Questions that cannot be resolved by this document + its ADR process should be raised as issues tagged `spec-gap` before code is written against an assumption.*

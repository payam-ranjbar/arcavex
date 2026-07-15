# Arcavex

Local-first, headless, deterministic, template-driven rendering engine built on skia-python.

A one-file YAML template plus data renders to an image or PDF with no project or configuration
required.

```bash
arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square -o out.png
```

The output extension selects the format — `.png`, `.jpg`/`.jpeg`, `.webp`, or `.pdf`. `--quality`
sets the lossy encoder quality (JPEG, lossy WebP) and `--lossless` selects lossless WebP. PDF is
raster-embedded RGB at the target DPI with the correct physical page size and trim/bleed boxes, so
`A4 + bleed` prints correctly. Every format is deterministic: identical inputs produce
byte-identical files, with no embedded timestamps or run ids.

Rendering without `-o` writes a deterministic default file,
`<template-stem>.<format>[.<locale>].png`, in the current directory and reports the chosen name
before rendering (on failure too, so you always learn what would have been written). The
`.<locale>` segment is present only when `--locale` is applied, so a `fa` render never
overwrites the `en` one. When a template declares exactly one format, or when no `--data` is
passed and `preview_data` exists, Arcavex infers the value and reports it (human output and the
`inferred` object in `--json`).

## Commands

| Command | Purpose |
|---|---|
| `render TEMPLATE [--data D] [--format F] [--locale L] [--style S] [-o OUT] [--quality Q] [--lossless]` | Render to an image or PDF; the `-o` extension (`.png`/`.jpg`/`.webp`/`.pdf`) picks the format. |
| `validate [TEMPLATE] [--data D] [--format F] [--locale L] [--style S] [--project P]` | Validate without rendering. Omit `TEMPLATE` to validate the current project (project mode). |
| `preview [TEMPLATE] [--data D] [--format F] [--locale L] [--style S] [--project P] [--watch]` | Render to a stable preview path; `--watch` re-renders on every save. Omit `TEMPLATE` to preview the current project. |
| `template new DIR` | Scaffold a minimal renderable template (template.yaml + data.yaml + README). |
| `template check PATH [--format F] [--locale L] [--style S]` | Validate a template without data (schema + structure + preview_data). |
| `template inspect PATH [--json]` | Report the authored contract: variables, formats, locales, nodes, functions, example data. |
| `template patch PATH [--set P --value V \| --remove P \| --insert-before P --node J \| --insert-after P --node J \| --ops-file F] [--base-sha256 H]` | Apply path-addressed set/remove/insert ops to a template on disk (comment-preserving); the AI mutation contract, also on the CLI. |
| `template split PATH` | Convert a one-file template into a split directory, losslessly. |
| `data set KEYPATH VALUE [--project P]` | Set a single value in the current project's data (VALUE parsed as JSON, else a string), then revalidate. |
| `data import [FILE] [--locale L] [--project P]` | Merge a YAML data document (or stdin) into the project's data under overlay semantics. |
| `asset add SOURCE [--project P]` | Ingest an image into the content-addressed store and report its reference. |
| `asset annotate SHA256 [--set k=v ... \| --annotations J]` | Write sidecar annotations (facing/focal_point/tags) onto an ingested asset. |
| `style list [--json]` | List installed style packs (palettes, presets, roles). |
| `style inspect NAME [--json]` | Show a style pack's palettes, fonts, effect presets, and role defaults. |
| `effects list [--json]` | List registered effects with their category and each param's type, default, and range. |
| `effects inspect NAME [--json]` | Show one effect's category and full parameter schema. |
| `doctor [--json]` | Check the environment (Python, Skia, ICU, fonts, exporters, cache, temp dir, paths, config) and engine version. |
| `explain ARC-XXX-NNN [--json]` | Explain a diagnostic code and its typical fix. |

### Projects, library, and provenance (§5)

| Command | Purpose |
|---|---|
| `template publish DIR --name N --version V [--no-default]` | Publish a template into the library as an immutable `N@V`; sets the default alias unless `--no-default`. |
| `template detach [--project P]` | Copy the project's library template into the project (disables version upgrades). |
| `project new DIR --template REF [--name N] [--style S] [--format F ...] [--locale L ...]` | Scaffold a renderable project pinning a template (`name@version` or a path). |
| `project clone DIR [--name N] [--project P]` | Clone a project into a new directory, reset to draft, dropping recorded runs. |
| `project set-status STATUS [--project P]` | Set the project status (`draft`/`review`/`approved`/`published`). |
| `project upgrade --to V [--yes] [--project P]` | Preview a template-version upgrade (structural stale paths + perceptual diff); `--yes` updates the pin. |
| `status [--project P]` | Show the current project's manifest and recorded-run count. |
| `render [--project P] [--format F] [--locale L] [--dpi N]` | With no template, render the discovered project's formats × locales into a recorded run. |
| `render TEMPLATE --record [...]` | Direct render that also writes a run manifest. |
| `list-runs [--project P] [--path DIR]` | List recorded runs newest first — the project's, or with `--path` the runs under a direct-mode `outputs/` directory. |
| `rerun outputs/<run>` | Reproduce a recorded run into a new run directory (byte-identical on the same engine + platform). |
| `diff outputs/<run-a> outputs/<run-b>` | Per-output pixel/perceptual diff plus template/data/asset/font/engine/option changes. |
| `batch <projects-glob> [--jobs N]` | Render every matched project in parallel jobs; output is byte-identical to serial. |

The CLI discovers `project.yaml` by walking upward from the current directory; `--project PATH`
overrides discovery. There is no persistent open-project state. A project references a library
template by `name@version` (bare `name` needs an explicit default alias) or by a filesystem
path. Recorded runs live under `outputs/<timestamp>_<shorthash>/` with a `manifest.json` pinning
every input by hash; the exported PNG bytes contain no timestamp or run id, so a same-platform
rerun reproduces them exactly.

Every command supports `--json`, `--no-color`, and `--quiet`. `--locale L` applies a declared
locale (direction, digit policy, font overrides, data overlay, and patch); requesting a locale
the template does not declare is a located error (`ARC-TPL-100`). `arcavex layout inspect
TEMPLATE [--data D] [--format F] [--locale L] [--json]` reports resolved geometry, and
`render`/`preview --debug` overlays node bounds, ids, baselines, and the safe-area margin.

Direct-mode `render TEMPLATE --record` runs (recorded outside a project) are `rerun`- and
`diff`-able by path, and `list-runs --path <outputs-dir>` lists them; `list-runs` with no project
and no `--path` falls back to a `./outputs` directory beside the current directory.

#### Project overrides (the PROJECT resolution layer)

A project can override its pinned template without forking it, using an override patch file:

- **Location & name:** `overrides/<template-name>.patch.yaml`, where `<template-name>` is the
  template's name before `@` (e.g. a project pinned to `ipen-poster@1.0.0` uses
  `overrides/ipen-poster.patch.yaml`). `project new` scaffolds an empty `overrides/` directory.
- **Contents:** a YAML **list** of patch operations — the same vocabulary as format/locale
  patches: `set`, `remove`, `insert_before`, `insert_after`, each addressing a node by
  `nodes.<id>[.<field>...]`. Example:
  ```yaml
  - set: nodes.background.style.fill
    value: '#00ff00'
  - remove: nodes.watermark
  ```
- **Resolution order:** the override is the **PROJECT layer**, applied last, after the style →
  template → format → locale layers (spec §5.4) — so it is the project's final structural word.
- **Provenance:** the applied override is captured in the run manifest by canonical content hash
  (`patch`), so `diff` attributes a patch-only change (`overrides` / `overrides.hash`) and
  `rerun` names it if the file changed on disk since the run was recorded (`ARC-RUN-002`).
  `project upgrade` reports override paths that no longer resolve against the target version.

#### Runtime configuration precedence (§6.3)

Settings resolve highest-first through **CLI flag → `ARCAVEX_*` env var → `project.yaml` →
`~/.arcavex/config.toml` (or `$ARCAVEX_HOME/config.toml`) → built-in default**. The wired setting
is the default render DPI:

- `--dpi N` on `render`/`batch`/`preview` (highest),
- `ARCAVEX_DPI=N` in the environment,
- `dpi: N` in `project.yaml` (project mode),
- `[render] dpi = N` in `config.toml`,
- otherwise each format renders at its own declared canvas DPI (the default).

`arcavex doctor` reports whether a `config.toml` is present and which layer the default DPI
resolves from.

`config.toml` also carries the resource-budget and cache tables that the budget diagnostics
(`ARC-RND-020..023`) and `doctor` point at — edit these to raise a limit a large render trips or
to resize the derived-image cache:

| Table / key | Default | What it bounds |
|---|---|---|
| `[budgets] max_dimension` | 30000 | Largest output width or height, in pixels (`ARC-RND-020`). |
| `[budgets] max_pixels` | 400000000 | Largest total output pixel count (`ARC-RND-021`). |
| `[budgets] max_surface_bytes` | 2000000000 | Peak render-surface memory, in bytes (`ARC-RND-022`). |
| `[budgets] max_wall_ms` | 120000 | Per-render wall-clock ceiling, in milliseconds (`ARC-RND-023`). |
| `[cache] derived_bytes` | 256000000 | Byte budget for the derived-image cache; both its memory and disk tiers are held under it, LRU-evicting the oldest variants (§4.7). |

## MCP authoring surface (§6.2)

Arcavex ships an optional [MCP](https://modelcontextprotocol.io) server so an AI agent can author
templates and projects through the same service API the CLI uses — never a second engine. Every
tool is a thin wrapper over one facade method and returns the **same** versioned pydantic result
the CLI's `--json` returns, with structured, coded, located diagnostics (never scraped text). The
transport is stdio only (no network).

| Command | Purpose |
|---|---|
| `mcp serve` | Start the stdio MCP authoring server (blocks until the client disconnects). |
| `mcp tools [--json]` | Print the tool catalog (names, descriptions, and input/output JSON schemas) for discovery. |

Wire it into an MCP client (e.g. Claude Desktop) as a stdio server running `arcavex mcp serve`.
The catalog (24 tools) mirrors the CLI: `arcavex_template_list`/`_inspect`/`_validate`/`_patch`,
`arcavex_project_create`/`_list`/`_status`/`_clone`/`_render`, `arcavex_render_record`,
`arcavex_data_set`/`_import`, `arcavex_asset_add`/`_annotate`,
`arcavex_style_list`/`_inspect`/`arcavex_effects_list`,
`arcavex_render_preview` (returns the PNG as image content, `debug=true` overlays the layout),
`arcavex_layout_inspect`, `arcavex_render`, `arcavex_run_list`/`_diff`/`_rerun`, and
`arcavex_diagnostic_explain`. Every tool delegates to a facade method that is also reachable from
the CLI/Python API, so MCP adds no exclusive capability (a linted boundary, spec §12.18).

The intended authoring loop (also the server's advertised `instructions`):

1. `arcavex_template_inspect` — read the contract: variables, formats, **locales**, node ids,
   functions, and example data, so the agent never infers the contract from raw source.
2. `arcavex_template_patch` — edit an addressed node (`nodes.<id>[.<field>]`). A leaf field in a
   fixed-vocabulary block (style/fit/paragraph/constraints) is validated before writing, so a
   typo (`fontsize` for `font_size`) is a located `ARC-TPL-051`, not a silent write; an op that
   does not name exactly one verb is a located `ARC-TPL-092`.
3. `arcavex_template_validate` → `arcavex_render_preview` (see the image) →
   `arcavex_layout_inspect` (resolved geometry, overlaps a compile-clean validate misses).
4. To author real content: `arcavex_project_create` → `arcavex_data_set` / `arcavex_data_import`
   (a keypath matching no declared variable warns with `ARC-TPL-112`) → `arcavex_project_render`
   for a recorded run that `arcavex_run_list`/`_diff`/`_rerun` then operate on.

## Template anatomy

A one-file template is a YAML mapping with these top-level sections:

- `version:` — template version string.
- `variables:` — declared inputs, e.g. `title: {type: string, required: true, default: ...,
  doc: ...}`. Types are `string`, `number`, `boolean`, `list`, `object`, `color`, `image`. A
  required variable with no value (and no default) is an error; a supplied value of the wrong
  type is reported. An explicit `null` in any data layer **binds null** — it is a value, not
  omission: it does not fall back to the declared `default`, and for a required variable it is
  still an error. Omitting a key entirely is what selects the default. (See ADR-0002.)
- `formats:` — named canvases, e.g. `square: {canvas: {width: 1080px, height: 1080px,
  dpi: 96}}`. A `canvas` may also declare `bleed: <dim>` (e.g. `bleed: 3mm`) for print-ready
  PDF output: the bleed grows the PDF's `MediaBox`/`BleedBox` uniformly beyond the `TrimBox`
  (the finished cut size), so `a4: {canvas: {width: 210mm, height: 297mm, dpi: 300, bleed: 3mm}}`
  renders a 216×303 mm media box around a 210×297 mm trim — an `A4 + bleed` print file in one
  command. Bleed only affects PDF page boxes; raster formats ignore it. PDF output is
  raster-embedded RGB at the target DPI (not vector, not CMYK/PDF-X — those stay deferred, §12),
  so text and shapes are rasterized pixels, not selectable vectors.
- `locales:` — per-locale `direction`/`digits`/`fonts`/`data`/`patch`, applied when the
  locale is requested with `--locale`. A `formats.<name>.patch` (and a locale `patch`) apply
  path-addressed `set`/`remove`/`insert_before`/`insert_after` operations to the node tree.
- `preview_data:` — values used **only** when no `--data` file is supplied (a preview
  fallback). Supplied data is never back-filled from `preview_data`.
- `style:` — opt into a style pack (`name@version` or `./file.yaml`). It supplies palettes
  addressable in expressions as `{{ palette.<name>[i] }}`, `effect_presets` a node references
  with `effect_preset:` (or `{preset: name}` in its `effects` list), and per-role defaults a
  text node pulls in with `style_role: heading|body|accent`. A node's own values override the
  role. `--style` on the CLI overrides the template's opt-in.
- `root:` — the node tree (a `group`). Any node may carry an ordered `effects:` list — the v1
  built-ins are blur, drop-shadow, glow, duotone, threshold, grade, posterize, palette-map,
  grain, noise, ink-bleed, halftone (a real SkSL dot-screen), channel-offset, torn-paper, and
  edge-wear. The renderer compiles the list into `geometry → fused color → raster → composite`;
  consecutive color effects fuse into one pass, and every effect declares the bounds expansion
  it needs so a shadow or blur is never clipped. Effect length params accept `pt`, `mm`, or `px`
  (a `px` value converts against the canvas DPI, like everywhere else); a bare number is points.
  Run `arcavex effects list` (or `effects inspect NAME`) to see each effect's parameters,
  defaults, and ranges without reading source. Shape nodes may use a `generator:` (`starburst`,
  `speech_bubble`, `qr_code`). See `examples/pop-art-grid` for a Warhol grid using all of this.

  **Effects reference** (run `arcavex effects list` for full param schemas):

  | Effect | Category | Key params |
  |---|---|---|
  | `blur` | raster | `radius` |
  | `drop-shadow` | composite | `dx`, `dy`, `blur`, `color` |
  | `glow` | composite | `radius`, `color` |
  | `grade` | color | `brightness`, `contrast`, `saturation` |
  | `duotone` | color | `shadow`, `highlight` |
  | `threshold` | color | `level`, `low`, `high` |
  | `posterize` | color | `levels` |
  | `palette-map` | raster | `colors` |
  | `grain` | raster | `amount` |
  | `noise` | raster | `amount` |
  | `ink-bleed` | raster | `radius` |
  | `halftone` | raster | `pitch`, `angle`, `ink` |
  | `channel-offset` | raster | `distance`, `angle` |
  | `torn-paper` | geometry | `amplitude`, `segment` |
  | `edge-wear` | raster | `amount` |

  When text sits over a textured effect panel (halftone, grain, noise), give it a solid plate or
  a high-contrast fill plus a dark drop-shadow — the dot/speckle mesh eats a same-toned label.
  pop-art-grid's title bar is a flat plate over the halftone for exactly this reason.

### Split templates

A larger template may be split into a directory without changing semantics — passing the
directory or its `template.yaml` is equivalent:

```text
event-poster/
├── template.yaml        # root node tree and metadata (always required)
├── schema.yaml          # optional split of `variables`
├── formats.yaml         # optional split of `formats`
├── locales.yaml         # optional split of `locales`
└── preview-data.yaml    # optional split of `preview_data`
```

Defining the same section both inline and in a sidecar is a located error (`ARC-TPL-097`), not
a precedence puzzle. `arcavex template split` performs the conversion.

### Nodes

Every node needs a stable `id` and a `type`. Types: `group`, `text`, `image`, `shape`
(`rect` | `rrect` | `circle`), `path`. Common fields: `visible: true|false` (a hidden node and
its subtree are not rendered), `z` (draw order within siblings), `style`, `constraints`,
`transform` (translation + `rotate`), and `mask` (`{component, params}` — built-ins:
`rounded_rect`, `circle`, `diamond_grid`). A `group` may set `layout: hstack|vstack` with
`gap`/`padding`/`main_align`/`cross_align` to flow its children. Any node may also carry
`effects:` and a template may opt into a `style:` pack (see above).

### Structural constructs

`repeat:` and `if:` are compiler-level constructs that expand into sibling nodes. A child is a
plain node, or one of these:

```yaml
children:
  - if: "{{ badge is not none }}"     # include the node only when the condition is truthy
    node:
      id: badge
      type: text
      text: "{{ badge }}"
      # …constraints…

  - repeat: "{{ guests }}"            # one sibling per item
    as: guest                         # each item is bound to `guest`
    key: "{{ guest.id }}"             # stable key -> expanded IDs `<id>[<key>]`
    node:
      id: row
      type: text
      text: "{{ guest.name }}"
      # …constraints…
```

Inside a `repeat`, `loop.index` (0-based), `loop.first`, and `loop.last` are available. The
`key:` is mandatory and must be unique per item; an index-derived key (`key: "{{ loop.index }}"`)
is allowed but warns, because reordering the data then changes node IDs. The iteration cap is
1000. Declaring both `repeat` and `if` on one child is an error (`ARC-TPL-061`); nest them
through a **wrapper group** — a construct's `node` is built directly and is not itself scanned
for nested constructs, so the inner construct must live in a group's `children` list:

```yaml
- repeat: "{{ guests }}"
  as: guest
  key: "{{ guest.id }}"
  node:                       # the repeated node is a group…
    type: group
    id: guest-row
    layout: vstack
    children:
      - if: "{{ guest.featured }}"   # …whose children hold the 'if' construct
        node: {id: star, type: text, text: "★", ...}
```

> Repeated siblings now lay out for real: put them in a `layout: hstack`/`vstack` group, or give
> each a distinct anchor computed from `loop.index` (expressions are evaluated inside constraint
> values, e.g. `top: "parent.top + {{ loop.index * 90 }}pt"`). A repeat whose siblings still
> resolve to identical bounds warns with `ARC-LAY-040`.

### Constraints and anchors

A node with a `constraints` block gives one horizontal anchor, one vertical anchor, and an
explicit `size: {w: ..., h: ...}`. Missing or duplicated position/size is a located `ARC-LAY`
error (unknown fields under `constraints`/`size` are rejected too, `ARC-TPL-051`).

**Anchors** pin one edge of this node to an edge of a reference, with an optional offset:

```yaml
constraints:
  anchor:
    top: title.bottom + 16pt      # a sibling edge: this node's top = title's bottom + 16pt
    start: parent.start + 56pt     # a parent edge
  size: {w: 84%, h: fit_content}
```

- **Reference** is `parent` or a **sibling id** in the same group. Sibling references resolve
  regardless of declaration order (forward refs work); a cycle is a located `ARC-LAY-052`
  naming the loop, and an unknown sibling is `ARC-LAY-053`. A rotated sibling contributes its
  post-transform bounding box.
- **Edges** are the six physical edges (`top`, `bottom`, `left`, `right`, `center_x`,
  `center_y`) plus the **logical** `start`/`end`, which resolve through the enclosing group's
  `direction` — in `ltr`, `start` = left and a `+` offset moves right; in `rtl`, `start` =
  right and a `+` offset moves left (reading order). This is what lets one template mirror.
- **Offsets** accept `{{ }}` expressions, evaluated *before* the offset is parsed, so per-item
  offsets work: `top: "parent.top + {{ loop.index * 90 }}pt"`. (Whitespace around the sign is
  fine.)

Horizontal anchor keys are `left`/`right`/`center_x`/`start`/`end`; vertical are
`top`/`bottom`/`center_y`.

**Sizes** — each axis of `size` is one of:

| Form | Meaning |
|---|---|
| `100px` / `40pt` / `20mm` | fixed |
| `62%` | percent of the parent's extent |
| `fill` | share the remaining space (equal split among `fill` siblings in a stack) |
| `fit_content` | the text's intrinsic size (text nodes only, `ARC-LAY-020` otherwise) |
| `{aspect: "3:4"}` or `aspect(3:4)` | derive this axis from the other (both spellings accepted) |

Any axis also accepts a mapping with `min`/`max` clamps and an explicit `value`, e.g.
`w: {value: 62%, min: 100px, max: 480px}` or `h: {aspect: "1:1", max: 240pt}`. Clamps apply in
every mode (including `fill` and stack shares); `aspect` derives from the *clamped* other axis.
`aspect` on both axes is `ARC-LAY-055`.

**Stacks** — a `group` with `layout: hstack|vstack` flows its children along a main axis with
`gap`, `padding`, `main_align` (`start`/`center`/`end`/`space_between`), and `cross_align`
(`start`/`center`/`end`/`stretch`); stack children take their position from the stack and must
not also declare an `anchor` (`ARC-LAY-054`). Under a resolved `rtl` direction an `hstack`
mirrors: the first child sits at the right edge and `main_align: start` packs from the right; a
`vstack`'s `cross_align` start/end mirror likewise. `wrap: true` is deferred (`ARC-LAY-056`).

**Text fit** — a text node may set `fit: {policy, overflow, min_size, max_lines}`:

- `policy`: `wrap` (default), `shrink_to_fit` (binary-search the largest size in
  `[min_size, font_size]` that fits — combine with `fit_content` height + `max_lines` to hug
  the shrunk result), or `truncate` (measured-prefix ellipsis, RTL-correct placement).
- `overflow`: `clip` (default), `allow`, or `error` (`ARC-LAY-050`, exit 1).
- `max_lines` caps the line count; with `h: fit_content` it also caps the box height.
- Non-convergent shrink and sub-line-height truncation emit `ARC-LAY-051` warnings with the
  measured numbers. `paragraph: {align, direction}` sets alignment (`start`/`end` follow the
  base direction) and BiDi base direction (`ltr`/`rtl`/`auto` = first strong character).

### Units and colors

Bare numbers are pixels; `px`, `pt`, `mm`, and `%` are also accepted (`1080` == `1080px`).
Colors are `#RGB`/`#RRGGBB`/`#RRGGBBAA`, `rgb()`/`rgba()` (channels must be in range), or a
named CSS basic color.

### Expressions and functions

String values may embed `{{ … }}` expressions (the only delimiter). If a value is exactly one
expression, its native type is preserved; embedded expressions stringify. Supported: literals,
dotted/indexed variable paths, arithmetic (`+ - * / %`), comparisons, boolean `and`/`or`/`not`,
ternary `a if cond else b`, string concat, and the `x | default(v)` operator. A literal `{{`
is written `\{{`. A missing variable is an error unless guarded with `| default(...)`.

Registered functions (call as `fn(args)` or pipe as `x | fn`):

| Function | Signature |
|---|---|
| `upper` | `upper(text: string) -> string` |
| `lower` | `lower(text: string) -> string` |
| `len` | `len(value: string\|list\|object) -> number` |
| `format` | `format(fmt: string, *args) -> string` (printf-style `{}`) |
| `min` | `min(*numbers \| list) -> number` |
| `max` | `max(*numbers \| list) -> number` |
| `round` | `round(value: number, ndigits: number = 0) -> number` |
| `locale_digits` | `locale_digits(text, locale: 'en'\|'latn'\|'fa'\|'arab') -> string` |
| `contrast_color` | `contrast_color(color: string) -> string` |

`arcavex template inspect --json` lists these with their signatures so an AI author need not
read source.

### Locales, data layering, and patches

`--locale L` applies the declared `locales.<L>` entry: `direction` (the root default and the
inherited default for undirected groups), `digits` (`fa`/`arab` map interpolated **numeric**
values and exact-match numeric expressions to Persian/Arabic-Indic digits; `en`/`latn` are the
Latin identity — string values are never remapped, so a time like `"17:00"` is localized in
data, not by the digit policy), `fonts` (family-substitution overrides), a `data` overlay, and
a `patch`.

**Effective data** is resolved in layers (later overrides earlier):

1. template `preview_data` / variable defaults (only when no `--data`),
2. template `locales.<L>.data` overlay (ships localized default strings),
3. the user `--data` file,
4. the user **sidecar** `data.<L>.yaml` next to the base data file (auto-applied for
   `--locale L`, if present).

So template data can localize defaults, user data always outranks template data, and the
locale-specific sidecar outranks the base user data. Both overlay applications are reported as
`inferred: data_overlay=…` inferences (shown even with `--json`; `--quiet` suppresses only the
human line). Overlay merge is recursive for mappings, whole-replace for scalars/lists, `null`
is a value, and the explicit YAML tag `!delete` (e.g. `key: !delete`) removes a key — the plain
string `"!delete"` is ordinary data. Passing a `data.<L>.yaml` sidecar directly to `--data`
(instead of the base file) is a common mistake; the missing-variable hint calls it out.

**Patches** (`formats.<name>.patch` and `locales.<L>.patch`) apply ordered
`set`/`remove`/`insert_before`/`insert_after` operations addressing authored node IDs
(`nodes.<id>[.<field>…]`, `nodes.root` included; field edits see through `repeat`/`if`
wrappers). `set` modifies an **existing** field — an unknown final path segment is a located
error, never a silent new key. Resolution order is format patch → locale patch, before
expressions.

`arcavex template inspect --resolved [--format F] [--locale L]` reports the resolved
direction/digits and each applied patch with the value it produced and its originating layer
(the last op on a path is marked effective), so you can answer "where did this value come
from?".

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success (including warnings) |
| 1 | validation or authoring error |
| 2 | invalid CLI usage |
| 3 | missing template, asset, or font |
| 4 | resource budget exceeded |
| 5 | internal failure (`ARC-INT-999`) |

## Known limitations (this build)

- **`fit_content` is text-only.** Sizing an image or group to its intrinsic content is not yet
  available (`ARC-LAY-020`); give those nodes an explicit size or an `aspect` ratio.
- **Wrapping stacks are deferred.** A stack with `wrap: true` reports `ARC-LAY-056` rather than
  faking multi-row flow; lay wrapped rows out with nested stacks for now.
- **Text metrics are paragraph-level** (skia-python 144 exposes no per-line/per-glyph boxes),
  so `max_lines` is approximated by dividing the measured paragraph height by a *measured*
  single-line height (not an invented constant), exact for uniform text; inspection reports
  paragraph bounds and baseline rather than per-glyph rectangles (ADR-0001).
- **`line_height` is not yet honored** (the bundled text stack exposes no strut override), so
  setting it is a located `ARC-TPL-053`; it is tracked in the ledger for a later phase.
- **Asset store is minimal.** The content-addressed store ingests assets by hash with sidecar
  metadata and enforces decode guards (max source bytes, max decoded pixels, format allowlist)
  before any decode, which is enough to pin assets in run manifests. (The derived-variant LRU
  cache — a large source downscaled once into the slot it occupies, under a byte budget — shipped
  in this build under `$ARCAVEX_HOME/cache/derived/`; see the config table above and `doctor`.)
- **Provenance is same-platform.** A rerun reproduces byte-identical output on the same engine
  version and platform (OS/arch); cross-platform reproduction is perceptual, not bit-exact, and
  `rerun` refuses to claim exact reproduction when the engine version or platform differs.

See the `examples/ipen-bilingual/` bilingual poster for locales, stacks, masks, sibling
anchors, rotation, and fit policies in one template, and
`arcavex-technical-design-spec-v1.1.md` for the full specification.

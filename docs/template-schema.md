# Template authoring reference

A template is a one-file YAML mapping (or a [split directory](#split-templates)) that, together
with data, renders to an image or PDF. This page is the complete authoring reference: every
top-level section, every node kind, the constraint/anchor system, sizing, stacks, fit policies,
units, colors, the expression language and its functions, locales and data layering, patches, and
effects. It is the deep companion to the [README](../README.md) overview; the CLI that drives it is
[cli.md](cli.md), and every error it can raise is in [diagnostics.md](diagnostics.md).

The authored contract of any template is machine-readable without reading source —
`arcavex template inspect PATH [--json]` reports its variables, formats, locales, node ids,
functions, and example data.

## Top-level sections

A one-file template is a YAML mapping with these sections:

| Section | Purpose |
|---|---|
| `version:` | Template version string. |
| `variables:` | Declared inputs (types, defaults, docs). |
| `formats:` | Named canvases (size + dpi, optional bleed and per-format patch). |
| `locales:` | Per-locale direction/digits/fonts/data/patch, applied with `--locale`. |
| `preview_data:` | Values used **only** when no `--data` is supplied (a preview fallback). |
| `style:` | Opt into a style pack (palettes, presets, roles). |
| `root:` | The node tree (a `group`). |

`seed:` (an integer for deterministic noise-like effects) is also accepted. These are the **only**
top-level sections: anything else is `ARC-TPL-065`, not a silently ignored extra.

> **Unknown fields are always rejected.** Every mapping on this page has a known vocabulary, and a
> field the engine does not read is a located error rather than a silent no-op — see
> [Unknown fields are always rejected](diagnostics.md#unknown-fields-are-always-rejected) for the
> code per scope. This is what makes a template's contract trustworthy: if it validates, every line
> in it does something.

### `variables`

Declared inputs, e.g. `title: {type: string, required: true, default: ..., doc: ...}`. A
declaration holds exactly `type`, `required`, `default`, `enum`, and `doc` (`ARC-TPL-067`
otherwise). Types are
`string`, `number`, `boolean`, `list`, `object`, `color`, `image`. A required variable with no
value and no default is an error (`ARC-TPL-014`); a supplied value of the wrong type is reported
(`ARC-TPL-015`); a value outside a declared `enum` is `ARC-TPL-017`.

An explicit `null` in any data layer **binds null** — it is a value, not omission: it does not fall
back to the declared `default`, and for a required variable it is still an error. Omitting a key
entirely is what selects the default. (See [ADR-0002](adr/0002-direction-inheritance-and-data-layering.md).)

### `formats`

Named canvases, e.g. `square: {canvas: {width: 1080px, height: 1080px, dpi: 96}}`. A `canvas` may
also declare `bleed: <dim>` (e.g. `bleed: 3mm`) for print-ready PDF output: the bleed grows the
PDF's `MediaBox`/`BleedBox` uniformly beyond the `TrimBox` (the finished cut size), so
`a4: {canvas: {width: 210mm, height: 297mm, dpi: 300, bleed: 3mm}}` renders a 216×303 mm media box
around a 210×297 mm trim — an `A4 + bleed` print file in one command. Bleed only affects PDF page
boxes; raster formats ignore it.

PDF output is raster-embedded RGB at the target DPI (not vector, not CMYK/PDF-X — those stay
deferred, see [known-limitations.md](known-limitations.md)), so text and shapes are rasterized
pixels, not selectable vectors.

A `formats.<name>.patch` applies path-addressed operations to the node tree for that format — see
[Patches](#patches).

### `locales`

Per-locale `direction`/`digits`/`fonts`/`data`/`patch`, applied when the locale is requested with
`--locale`. Requesting a locale the template does not declare is a located error (`ARC-TPL-100`).
See [Locales, data layering, and patches](#locales-data-layering-and-patches).

### `preview_data`

Values used **only** when no `--data` file is supplied. Supplied data is never back-filled from
`preview_data`.

### `style`

Opt into a style pack (`name@version` or `./file.yaml`). It supplies palettes addressable in
expressions as `{{ palette.<name>[i] }}`, `effect_presets` a node references with `effect_preset:`
(or `{preset: name}` in its `effects` list), and per-role defaults a text node pulls in with
`style_role: heading|body|accent`. A node's own values override the role. `--style` on the CLI
overrides the template's opt-in. Inspect installed packs with `arcavex style list` /
`arcavex style inspect NAME`.

## Split templates

A larger template may be split into a directory without changing semantics — passing the directory
or its `template.yaml` is equivalent:

```text
event-poster/
├── template.yaml        # root node tree and metadata (always required)
├── schema.yaml          # optional split of `variables`
├── formats.yaml         # optional split of `formats`
├── locales.yaml         # optional split of `locales`
└── preview-data.yaml    # optional split of `preview_data`
```

Defining the same section both inline and in a sidecar is a located error (`ARC-TPL-097`), not a
precedence puzzle. `arcavex template split` performs the conversion losslessly.

## Nodes

Every node needs a stable `id` and a `type`. Types: `group`, `text`, `image`,
`shape` (`rect` | `rrect` | `circle`), `path`.

| Node kind | Notes |
|---|---|
| `group` | A container. May set `layout: hstack\|vstack` (with `gap`/`padding`/`main_align`/`cross_align`) to flow its children, and a `direction`. |
| `text` | Live shaped text (`text:` or a `runs:` list). Supports `style`, `paragraph`, and `fit` policies. |
| `image` | References an `asset:` (template-relative path). `fit:` is `fill`/`contain`/`cover`. |
| `shape` | `rect`, `rrect`, or `circle`; or a `generator:` (`starburst`, `speech_bubble`, `qr_code`). |
| `path` | A vector path. Geometry effects (e.g. `torn-paper`) apply to `shape`/`path` nodes only. |

Common fields on any node: `visible: true|false` (a hidden node and its subtree are not rendered),
`z` (draw order within siblings), `style`, `style_role`, `constraints`, `transform`
(`translate`, `rotate`, `scale`, `origin` — composed as translate ∘ rotate ∘ scale about the
pivot), and `mask` (`{component, params}` — built-ins: `rounded_rect`, `circle`,
`diamond_grid`). Any node may also carry an `effects:` list or an `effect_preset:` shorthand.

Beyond those, each kind adds only its own fields — and nothing else is accepted (`ARC-TPL-064`):

| Kind | Additional fields |
|---|---|
| `group` | `children`, `direction`, `clip`, `layout`, `gap`, `padding`, `main_align`, `cross_align` |
| `text` | `text`, `runs`, `paragraph`, `fit` |
| `image` | `asset`, `fit` |
| `shape` | `shape`, `generator`, `params` |
| `path` | `d` |

There is **no per-node `condition:`** — gate a node with the structural `if:`/`node:` construct
below. Paint properties (`opacity`, `color`, `font_size`, …) live in `style:`, not on the node;
size lives in `constraints.size`, position in `constraints.anchor`, and rotation/scale in
`transform`.
Writing any of them at node level is a located error whose hint names the real home.

### Structural constructs — `repeat` and `if`

`repeat:` and `if:` are compiler-level constructs that expand into sibling nodes. A child is a plain
node, or one of these:

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

Inside a `repeat`, `loop.index` (0-based), `loop.first`, and `loop.last` are available. The `key:`
is mandatory and must be unique per item (`ARC-TPL-055`/`ARC-TPL-058`); an index-derived key
(`key: "{{ loop.index }}"`) is allowed but warns (`ARC-TPL-057`), because reordering the data then
changes node IDs. The iteration cap is 1000 (`ARC-TPL-063`).

Declaring both `repeat` and `if` on one child is an error (`ARC-TPL-061`); nest them through a
**wrapper group** — a construct's `node` is built directly and is not itself scanned for nested
constructs, so the inner construct must live in a group's `children` list:

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

Repeated siblings lay out for real: put them in a `layout: hstack`/`vstack` group, or give each a
distinct anchor computed from `loop.index` (expressions are evaluated inside constraint values,
e.g. `top: "parent.top + {{ loop.index * 90 }}pt"`). A repeat whose siblings still resolve to
identical bounds warns with `ARC-LAY-040`.

## Constraints and anchors

A node with a `constraints` block gives one horizontal anchor, one vertical anchor, and an explicit
`size: {w: ..., h: ...}`. Missing or duplicated position/size is a located `ARC-LAY` error
(`ARC-LAY-030`/`031`/`032`); unknown fields under `constraints`/`size` are rejected too
(`ARC-TPL-051`).

**Anchors** pin one edge of this node to an edge of a reference, with an optional offset:

```yaml
constraints:
  anchor:
    top: title.bottom + 16pt       # a sibling edge: this node's top = title's bottom + 16pt
    start: parent.start + 56pt     # a parent edge
  size: {w: 84%, h: fit_content}
```

- **Reference** is `parent` or a **sibling id** in the same group. Sibling references resolve
  regardless of declaration order (forward refs work); a cycle is a located `ARC-LAY-052` naming the
  loop, and an unknown sibling is `ARC-LAY-053`. A transformed sibling contributes its post-transform
  bounding box — the AABB after its translate, rotate, and scale.
- **Edges** are the six physical edges (`top`, `bottom`, `left`, `right`, `center_x`, `center_y`)
  plus the **logical** `start`/`end`, which resolve through the enclosing group's `direction` — in
  `ltr`, `start` = left and a `+` offset moves right; in `rtl`, `start` = right and a `+` offset
  moves left (reading order). This is what lets one template mirror. Group direction inherits from
  the nearest enclosing group that declares one; the root default comes from the requested locale
  ([ADR-0002](adr/0002-direction-inheritance-and-data-layering.md)).
- **Offsets** accept `{{ }}` expressions, evaluated *before* the offset is parsed, so per-item
  offsets work: `top: "parent.top + {{ loop.index * 90 }}pt"`. (Whitespace around the sign is fine.)

Horizontal anchor keys are `left`/`right`/`center_x`/`start`/`end`; vertical are
`top`/`bottom`/`center_y`.

### Sizes

Each axis of `size` is one of:

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

### Stacks

A `group` with `layout: hstack|vstack` flows its children along a main axis with `gap`, `padding`,
`main_align` (`start`/`center`/`end`/`space_between`), and `cross_align`
(`start`/`center`/`end`/`stretch`); stack children take their position from the stack and must not
also declare an `anchor` (`ARC-LAY-054`). Under a resolved `rtl` direction an `hstack` mirrors: the
first child sits at the right edge and `main_align: start` packs from the right; a `vstack`'s
`cross_align` start/end mirror likewise. `wrap: true` is deferred (`ARC-LAY-056`).

### Text fit

A text node may set `fit: {policy, overflow, min_size, max_lines}`:

- `policy`: `wrap` (default), `shrink_to_fit` (binary-search the largest size in
  `[min_size, font_size]` that fits — combine with `fit_content` height + `max_lines` to hug the
  shrunk result), or `truncate` (measured-prefix ellipsis, RTL-correct placement).
- `overflow`: `clip` (default), `allow`, or `error` (`ARC-LAY-050`, exit 1).
- `max_lines` caps the line count; with `h: fit_content` it also caps the box height. When
  `shrink_to_fit` reaches its `min_size` floor and the text still needs more lines than the cap
  allows, `overflow: error` reports `ARC-LAY-057` — line count vs cap and the floor reached —
  instead of `ARC-LAY-050`. The box height is not the constraint there, so enlarging it cannot
  help; widen the box, lower `min_size`, or raise `max_lines`.
- Non-convergent shrink and sub-line-height truncation emit `ARC-LAY-051` warnings with the measured
  numbers. `paragraph: {align, direction}` sets alignment (`start`/`end` follow the base direction)
  and BiDi base direction (`ltr`/`rtl`/`auto` = first strong character).

Text metrics are paragraph-level and `line_height` is not yet honored — see
[known-limitations.md](known-limitations.md).

## Units and colors

Bare numbers are pixels; `px`, `pt`, `mm`, and `%` are also accepted (`1080` == `1080px`). Colors
are `#RGB`/`#RRGGBB`/`#RRGGBBAA`, `rgb()`/`rgba()` (channels must be in range), or a named CSS basic
color. An unparseable color is `ARC-IR-030`.

## Expressions and functions

String values may embed `{{ … }}` expressions (the only delimiter). If a value is exactly one
expression, its native type is preserved; embedded expressions stringify. Supported: literals,
dotted/indexed variable paths, arithmetic (`+ - * / %`), comparisons, boolean `and`/`or`/`not`,
ternary `a if cond else b`, string concat, and the `x | default(v)` operator. A literal `{{` is
written `\{{`. A missing variable is an error (`ARC-TPL-014`) unless guarded with `| default(...)`.

Registered functions (call as `fn(args)` or pipe as `x | fn`) — the authoritative list is the
`TemplateFunction` registry (`arcavex.builtin.template_fns`), also emitted by
`arcavex template inspect --json`:

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

## Locales, data layering, and patches

`--locale L` applies the declared `locales.<L>` entry: `direction` (the root default and the
inherited default for undirected groups), `digits` (`fa`/`arab` map interpolated **numeric** values
and exact-match numeric expressions to Persian/Arabic-Indic digits; `en`/`latn` are the Latin
identity — string values are never remapped, so a time like `"17:00"` is localized in data, not by
the digit policy), `fonts` (family-substitution overrides), a `data` overlay, and a `patch`.

**Effective data** is resolved in layers (later overrides earlier):

1. template `preview_data` / variable defaults (only when no `--data`),
2. template `locales.<L>.data` overlay (ships localized default strings),
3. the user `--data` file,
4. the user **sidecar** `data.<L>.yaml` next to the base data file (auto-applied for `--locale L`,
   if present).

So template data can localize defaults, user data always outranks template data, and the
locale-specific sidecar outranks the base user data. Both overlay applications are reported as
`inferred: data_overlay=…` inferences (shown even with `--json`; `--quiet` suppresses only the human
line). Overlay merge is recursive for mappings, whole-replace for scalars/lists, `null` is a value,
and the explicit YAML tag `!delete` (e.g. `key: !delete`) removes a key — the plain string
`"!delete"` is ordinary data. Passing a `data.<L>.yaml` sidecar directly to `--data` (instead of the
base file) is a common mistake; the missing-variable hint calls it out. Full rationale in
[ADR-0002](adr/0002-direction-inheritance-and-data-layering.md).

### Patches

`formats.<name>.patch` and `locales.<L>.patch` apply ordered
`set`/`remove`/`insert_before`/`insert_after` operations addressing authored node IDs
(`nodes.<id>[.<field>…]`, `nodes.root` included; field edits see through `repeat`/`if` wrappers).
`set` modifies an **existing** field — an unknown final path segment is a located error
(`ARC-TPL-092`), never a silent new key. Resolution order is style → template → format patch →
locale patch → project override, before expressions.

`arcavex template inspect --resolved [--format F] [--locale L]` reports the resolved
direction/digits and each applied patch with the value it produced and its originating layer (the
last op on a path is marked effective), so you can answer "where did this value come from?":

```console
$ arcavex template inspect examples/future-archive-poster/template.yaml \
    --resolved --format a4 --locale fa
resolved format=a4 locale=fa direction=rtl digits=fa style=-
  nodes.hero.constraints.size.h = 38% <- format:a4 (set)
  nodes.title.style.font_size = 48pt <- format:a4 (set)
  nodes.venue.constraints.size.w = 92% <- format:a4 (set)
  nodes.venue.style.font_size = 22pt <- format:a4 (set)
  nodes.subtitle.fit.max_lines = 3 <- format:a4 (set)
  nodes.accent-bar.transform.rotate = 4 <- locale:fa (set)
```

## Effects

Any node may carry an ordered `effects:` list. The renderer compiles the list into
`geometry → fused color → raster → composite`; consecutive color effects fuse into one pass, and
every effect declares the bounds expansion it needs so a shadow or blur is never clipped. Effect
length params accept `pt`, `mm`, or `px` (a `px` value converts against the canvas DPI); a bare
number is points. An entry is a name, a `{name, params}` mapping, or a `{preset: name}` reference to
a style pack's `effect_presets`.

Run `arcavex effects list` (or `arcavex effects inspect NAME`) for each effect's parameters,
defaults, and ranges — that CLI is the source of truth. The v1 built-ins:

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
| `halftone` | raster | `pitch`, `angle`, `ink` (a real SkSL dot-screen) |
| `channel-offset` | raster | `distance`, `angle` |
| `torn-paper` | geometry | `amplitude`, `segment` (shape/path nodes only) |
| `edge-wear` | raster | `amount` |

When text sits over a textured effect panel (halftone, grain, noise), give it a solid plate or a
high-contrast fill plus a dark drop-shadow — the dot/speckle mesh eats a same-toned label.
`examples/graphic-style-lab`'s title bar is a flat plate over the halftone for exactly this reason.

Shape nodes may use a `generator:` (`starburst`, `speech_bubble`, `qr_code`). See
`examples/graphic-style-lab` for a Warhol grid using effects, loops, and style packs together.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success (including warnings) |
| 1 | validation or authoring error |
| 2 | invalid CLI usage |
| 3 | missing template, asset, or font |
| 4 | resource budget exceeded |
| 5 | internal failure (`ARC-INT-999`) |

## See also

- [cli.md](cli.md) — the commands that render, validate, inspect, and patch a template.
- [diagnostics.md](diagnostics.md) — every `ARC-…` code, grouped, with `arcavex explain`.
- [tutorials/](tutorials/) — build a template from scratch, and a bilingual template worked example.
- [known-limitations.md](known-limitations.md) — what is deferred (`fit_content` scope, wrapping
  stacks, `line_height`, vector PDF/CMYK).

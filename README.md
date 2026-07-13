# Arcavex

Local-first, headless, deterministic, template-driven rendering engine built on skia-python.

A one-file YAML template plus data renders to a PNG with no project or configuration required.

```bash
arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square -o out.png
```

Rendering without `-o` writes a deterministic default file, `<template-stem>.<format>.png`,
in the current directory and reports the chosen name before rendering (on failure too, so you
always learn what would have been written). When a template declares exactly one format, or
when no `--data` is passed and `preview_data` exists, Arcavex infers the value and reports it
(human output and the `inferred` object in `--json`).

## Commands

| Command | Purpose |
|---|---|
| `render TEMPLATE [--data D] [--format F] [--locale L] [-o OUT]` | Render to PNG. |
| `validate TEMPLATE [--data D] [--format F] [--locale L]` | Validate without rendering. |
| `preview TEMPLATE [--data D] [--format F] [--locale L] [--watch]` | Render to a stable preview path; `--watch` re-renders on every save. |
| `template new DIR` | Scaffold a minimal renderable template (template.yaml + data.yaml + README). |
| `template check PATH [--format F] [--locale L]` | Validate a template without data (schema + structure + preview_data). |
| `template inspect PATH [--json]` | Report the authored contract: variables, formats, nodes, functions, example data. |
| `template split PATH` | Convert a one-file template into a split directory, losslessly. |
| `doctor [--json]` | Check the environment (Python, Skia, ICU, fonts, temp dir, paths) and engine version. |
| `explain ARC-XXX-NNN [--json]` | Explain a diagnostic code and its typical fix. |

Every command supports `--json`, `--no-color`, and `--quiet`. `--locale L` applies a declared
locale (direction, digit policy, font overrides, data overlay, and patch); requesting a locale
the template does not declare is a located error (`ARC-TPL-100`). `arcavex layout inspect
TEMPLATE [--data D] [--format F] [--locale L] [--json]` reports resolved geometry, and
`render`/`preview --debug` overlays node bounds, ids, baselines, and the safe-area margin.

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
  dpi: 96}}`.
- `locales:` — per-locale `direction`/`digits`/`fonts`/`data`/`patch`, applied when the
  locale is requested with `--locale`. A `formats.<name>.patch` (and a locale `patch`) apply
  path-addressed `set`/`remove`/`insert_before`/`insert_after` operations to the node tree.
- `preview_data:` — values used **only** when no `--data` file is supplied (a preview
  fallback). Supplied data is never back-filled from `preview_data`.
- `root:` — the node tree (a `group`).

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
`gap`/`padding`/`main_align`/`cross_align` to flow its children. Effects and style packs are
later phases and are rejected with a "not supported in this build" diagnostic.

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

- **Effects and style packs are Phase 3**, and are rejected with located diagnostics
  (`ARC-FX-900`, `ARC-TPL-093/094`).
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

See the `examples/ipen-bilingual/` bilingual poster for locales, stacks, masks, sibling
anchors, rotation, and fit policies in one template, and
`arcavex-technical-design-spec-v1.1.md` for the full specification.

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
  type is reported. Supplying an explicit `null` for an optional variable is the same as
  omitting it.
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

A node with a `constraints` block must give one horizontal anchor (`left` | `right` |
`center_x`), one vertical anchor (`top` | `bottom` | `center_y`), and an explicit
`size: {w: ..., h: ...}`. Sizes are `fixed` (`100px`), `%` (`62%`), `fill`, or `fit_content`
(text only). Missing or duplicated position/size is a located `ARC-LAY` error.

Anchors reference a parent edge with an optional **literal** offset: `parent.top`,
`parent.left+48px`, `parent.center_y-70px`. Whitespace around the sign is tolerated
(`parent.left + 48px`). `{{ }}` expressions are **not** evaluated inside constraints.

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
| `locale_digits` | `locale_digits(text, locale: 'en'\|'fa') -> string` |
| `contrast_color` | `contrast_color(color: string) -> string` |

`arcavex template inspect --json` lists these with their signatures so an AI author need not
read source.

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
  so `max_lines` is approximated from measured height and inspection reports paragraph bounds
  and baseline rather than per-glyph rectangles (ADR-0001).

See the `examples/ipen-bilingual/` bilingual poster for locales, stacks, masks, sibling
anchors, rotation, and fit policies in one template, and
`arcavex-technical-design-spec-v1.1.md` for the full specification.

# Arcavex

Local-first, headless, deterministic, template-driven rendering engine built on skia-python.

Phase 0 slice: a one-file YAML template plus data renders to a PNG with no project or
configuration required.

```bash
arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square -o out.png
```

Rendering without `-o` writes a deterministic default file, `<template-stem>.<format>.png`,
in the current directory and reports the chosen name. When a template declares exactly one
format, or when no `--data` is passed and `preview_data` exists, Arcavex infers the value and
reports it (human output and the `inferred` object in `--json`).

## Template anatomy

A one-file template is a YAML mapping with these top-level sections:

- `version:` — template version string.
- `variables:` — declared inputs, e.g. `title: {type: string, required: true, default: ...,
  doc: ...}`. Types are `string`, `number`, `boolean`, `list`, `object`, `color`, `image`. A
  required variable with no value (and no default) is an error; a supplied value of the wrong
  type is reported.
- `formats:` — named canvases, e.g. `square: {canvas: {width: 1080px, height: 1080px,
  dpi: 96}}`.
- `preview_data:` — values used **only** when no `--data` file is supplied (a preview
  fallback). Supplied data is never back-filled from `preview_data`.
- `root:` — the node tree (a `group`).

### Nodes

Every node needs a stable `id` and a `type`. Types: `group`, `text`, `image`, `shape`
(`rect` | `rrect` | `circle`), `path`. Common fields: `visible: true|false` (a hidden node and
its subtree are not rendered), `z` (draw order within siblings), `style`, `constraints`.
`hstack`/`vstack`, `repeat`/`if`, effects, and masks are later phases and are rejected with a
"not supported in this build" diagnostic rather than silently ignored.

### Constraints and anchors

A node with a `constraints` block must give one horizontal anchor (`left` | `right` |
`center_x`), one vertical anchor (`top` | `bottom` | `center_y`), and an explicit
`size: {w: ..., h: ...}`. Sizes are `fixed` (`100px`), `%` (`62%`), `fill`, or `fit_content`
(text only). Missing or duplicated position/size is a located `ARC-LAY` error.

Anchors reference a parent edge with an optional offset: `parent.top`, `parent.left+48px`,
`parent.center_y-70px`. Whitespace around the sign is tolerated (`parent.left + 48px`).

### Units and colors

Bare numbers are pixels; `px`, `pt`, `mm`, and `%` are also accepted (`1080` == `1080px`).
Colors are `#RGB`/`#RRGGBB`/`#RRGGBBAA`, `rgb()`/`rgba()` (channels must be in range), or a
named CSS basic color.

### Expressions

String values may embed `{{ … }}` expressions (the only delimiter). If a value is exactly one
expression, its native type is preserved; embedded expressions stringify. Supported:
literals, dotted/indexed variable paths, arithmetic (`+ - * / %`), comparisons, boolean
`and`/`or`/`not`, ternary `a if cond else b`, string concat, the `x | default(v)` operator,
and the functions `len()`, `upper()`, `lower()`, `format()`. A literal `{{` is written `\{{`.
A missing variable is an error unless guarded with `| default(...)`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success (including warnings) |
| 1 | validation or authoring error |
| 2 | invalid CLI usage |
| 3 | missing template, asset, or font |
| 4 | resource budget exceeded |
| 5 | internal failure (`ARC-INT-999`) |

See `arcavex-technical-design-spec-v1.1.md` for the full specification.

# Building a template from scratch

This walkthrough goes from an empty directory to a rendered card, introducing nodes, constraints,
anchors, sizes, stacks, and fit policies along the way. The full reference for every construct is
[template-schema.md](../template-schema.md); this is the guided path.

## 1. Scaffold

`arcavex template new` writes a minimal, immediately-renderable template — a good starting point that
already exercises variables, an `if` construct, and the `| default(...)` operator.

```console
$ arcavex template new ./card
Created ./card (render with --format square)
```

That produces three files:

```text
card/
├── template.yaml   # the node tree, variables, formats, preview_data
├── data.yaml       # sample content
└── README.md
```

Render it straight away — with no `--data`, `preview_data` supplies the content, reported as an
inference:

```console
$ arcavex render ./card --format square -o card.png
inferred: data=preview_data
Rendered card.png
```

## 2. Read the scaffold

The scaffolded `template.yaml` is worth reading top to bottom. Its shape is the shape of every
template ([top-level sections](../template-schema.md#top-level-sections)):

- **`variables:`** declares the inputs — `title` (required), `subtitle` and `badge` (optional). An
  optional variable with no default reads as `none` when omitted.
- **`formats:`** declares two canvases, `square` (1080×1080 @ 96dpi) and `story` (1080×1920).
- **`preview_data:`** supplies `title` so a data-less render works.
- **`root:`** is a `group` whose `children` are the scene.

## 3. Nodes

Every node has a stable `id` and a `type`. The scaffold uses three of the five
[node kinds](../template-schema.md#nodes):

```yaml
- id: background
  type: shape
  shape: rect
  style: {fill: "#0f1020"}
  # …constraints…

- id: title
  type: text
  text: "{{ title }}"
  style: {font: Inter, font_size: 84px, font_weight: 800, color: "#ffffff", align: start}
  # …constraints…
```

`text` nodes carry an expression in `text:` (here `{{ title }}` binds the variable); `shape` nodes
draw `rect`/`rrect`/`circle`; `image` nodes reference a template-relative `asset:`.

## 4. Constraints and anchors

Each positioned node gives **one horizontal anchor, one vertical anchor, and an explicit size**.
An anchor pins one edge of this node to an edge of a reference (`parent` or a sibling id):

```yaml
constraints:
  anchor: {left: parent.left+64px, top: parent.center_y-60px}
  size: {w: 82%, h: fit_content}
```

- Physical edges: `top`/`bottom`/`left`/`right`/`center_x`/`center_y`. The **logical** `start`/`end`
  edges resolve through the group's direction — the key to a mirrored RTL layout (covered in the
  `examples/future-archive-poster/`).
- Offsets accept units (`+64px`, `+16pt`, `-6mm`) and even `{{ }}` expressions, so per-item offsets
  work.
- Missing or duplicated anchors are located errors (`ARC-LAY-030`/`031`); anchoring to a sibling that
  does not exist is `ARC-LAY-053`, and a cycle is `ARC-LAY-052`.

## 5. Sizes

The scaffold's title uses `w: 82%` (percent of the parent) and `h: fit_content` (the text's intrinsic
height). The [size forms](../template-schema.md#sizes) are: fixed (`100px`/`40pt`/`20mm`), percent,
`fill` (share remaining space), `fit_content` (text nodes only), and `aspect(W:H)`. Any axis can add
`min`/`max` clamps: `w: {value: 62%, min: 100px, max: 480px}`.

## 6. Conditionals and stacks

The scaffold's footer is an `if` construct — the node is included only when `badge` is supplied:

```yaml
- if: "{{ badge is not none }}"
  node:
    id: badge
    type: text
    text: "{{ badge }}"
    # …
```

Uncomment `badge:` in `data.yaml` and it appears. For a **dynamic list** of nodes, use a `repeat`
over a list with a stable `key`, and lay the results out with a stack:

```yaml
root:
  type: group
  layout: vstack          # flow children top-to-bottom
  gap: 12pt
  padding: 48pt
  children:
    - repeat: "{{ items }}"
      as: item
      key: "{{ item.id }}"
      node:
        id: row
        type: text
        text: "{{ item.label }}"
        style: {font: Inter, font_size: 32px, color: "#ffffff"}
        size: {w: fill, h: fit_content}
```

A `group` with `layout: hstack|vstack` positions its own children with `gap`, `padding`,
`main_align`, and `cross_align` — so stack children must **not** also declare an `anchor`
(`ARC-LAY-054`). Under a resolved RTL direction an `hstack` mirrors automatically. (`repeat`, `key`,
and stack mechanics in full: [template-schema.md](../template-schema.md#structural-constructs--repeat-and-if).)

## 7. Fit policies

Long real-world values must stay readable. A text node's `fit:` block controls that:

```yaml
- id: title
  type: text
  text: "{{ title }}"
  fit: {policy: shrink_to_fit, min_size: 40px, max_lines: 2, overflow: clip}
  size: {w: 82%, h: fit_content}
```

- `wrap` (default), `shrink_to_fit` (binary-search the largest fitting size in `[min_size, font_size]`),
  or `truncate` (measured-prefix ellipsis).
- `overflow`: `clip` (default), `allow`, or `error` (fails with `ARC-LAY-050`).
- Non-convergent shrink warns with `ARC-LAY-051` and the measured numbers.

## 8. Validate, inspect, render

Three commands close the loop:

```console
$ arcavex template check ./card --format square      # schema + structure, no data
OK template is valid

$ arcavex layout inspect ./card --format square       # resolved geometry + overlaps
inferred: data=preview_data
canvas 810x810pt (1080x1080px @ 96dpi) format=square locale=-
root group bounds (0.0, 0.0, 810.0, 810.0)pt
  paint (0.0, 0.0, 810.0, 810.0)pt
  …
coverage: 100% of canvas

$ arcavex render ./card --format square -o card.png
inferred: data=preview_data
Rendered card.png
```

`layout inspect` shows the resolved bounds and any sibling overlaps — geometry a compile-clean
`check`/`validate` cannot see. Use it whenever a node lands somewhere unexpected. The scaffold's
nodes all clear each other, so it prints no `overlaps` section at all.

Each node prints two boxes: `bounds` is the layout box, and `paint` is that box grown by rotation
and by any effect's declared bounds expansion. Overlaps are split the same way — a `content`
overlap means the boxes really intersect, a `touch` is a graze of a point or a corner nick, and
*effect spill* means only the grown boxes do (a drop-shadow reaching over a neighbour). Fix the
first; the other two are usually the intended look. A label sitting on the panel painted beneath
it, or inside a stroke-only frame, is structure and is not listed at all. See
[overlap kinds](../cli.md#overlap-kinds).

## Next

- Make it bilingual → see `examples/future-archive-poster/`, which renders EN and FA from one tree.
- The complete authoring vocabulary → [template-schema.md](../template-schema.md).
- Every command and flag → [cli.md](../cli.md).

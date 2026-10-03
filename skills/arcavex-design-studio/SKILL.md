---
name: arcavex-design-studio
description: Author, inspect, patch, validate, preview, and render reusable posters, event graphics, social tiles, covers, and bilingual or RTL designs with the Arcavex CLI. Use for Arcavex briefs, brand kits, typography, assets, multiple formats or locales, and custom Arcavex effects. Not for one-off raster edits.
---

# Arcavex Design Studio

<!-- engine-build -->

Use the CLI as the primary surface. Ground design decisions in the supplied brief, preserve brand
constraints, and never invent factual copy. Build one reusable template with data and explicit
format/locale variations. Start a small working template early; read additional references only
when needed. The live binary's help and diagnostics are authoritative.

## 0. Identify the build and set up once

```bash
arcavex --version
arcavex doctor --json
arcavex render --help
```

Compare `--version` with the engine build above. If versions or commits differ, use the running
binary's `--help` and refresh this skill with `arcavex skill install --force`. A header with no
commit is an unpinned source copy; do not claim it identifies an installed release.

If `arcavex` is absent from PATH, locate the installed executable once. The standard Windows
standalone location is `%LOCALAPPDATA%\Programs\Arcavex\arcavex.exe`; use its actual install
directory if different. Add that directory to the shell's PATH once and reuse it. Do not try
Python module entry points for a standalone installation. A source checkout may use its venv's
`arcavex` script. If no engine is available, report the missing setup.

```bash
cd /path/to/campaign
mkdir -p .arcavex-home outputs
# This directory is discovered automatically from the working directory and its parents.
# An explicitly set ARCAVEX_HOME takes precedence; unset it to use automatic discovery.
arcavex doctor --json
```

Keep that working directory for later commands. For a campaign outside the current directory,
set `ARCAVEX_HOME` once to its absolute `.arcavex-home` path. PowerShell:
`$env:ARCAVEX_HOME = 'C:\campaign\.arcavex-home'`. Use paths that exist in the current shell:
Git Bash `/tmp` and Windows `C:\tmp` are different locations.

Install only `arcavex-design-studio` from the same engine build. If an old `arcavex-poster-studio`
copy is also loaded from `.claude/skills` or `.agents/skills`, flag the conflicting installation;
preserve any local edits before retiring it. Skill installation does not delete other skills.

## 1. Scaffold, then inspect

```bash
arcavex template new templates/card
arcavex template inspect templates/card --json
arcavex font list --json
arcavex effects list --json
```

Use `template new` rather than reconstructing the language from a large production template.
Its preview data and `en` locale allow a first render immediately. Fonts must use the exact family
reported by `font list` or `font add FILE.ttf --json`, not a filename. This build reads the font's
OpenType family table and registers that alias consistently across platforms. Older Windows
builds may report `Archivo` for `Archivo Black`; check the running build and use a locale `fonts`
mapping when reproducing an old pin rather than repeatedly guessing family names.

For a small image card, place `photo.png` beside the following single-file template:

```yaml
version: 0.1.0
locales: {en: {direction: ltr, digits: en}}
formats:
  square: {canvas: {width: 600px, height: 600px, dpi: 96}}
variables:
  title: {type: string, required: true}
  photo: {type: image, required: true}
preview_data: {title: "A short title", photo: photo.png}
root:
  id: root
  type: group
  children:
    - id: photo
      type: image
      asset: "{{ photo }}"
      fit: cover
      constraints:
        anchor: {top: parent.top, start: parent.start}
        size: {w: fill, h: 60%}
    - id: title
      type: text
      text: "{{ title }}"
      style: {font: Inter, font_size: 36pt, color: "#111111"}
      fit: {policy: shrink_to_fit, min_size: 18pt, max_lines: 2}
      constraints:
        anchor: {top: parent.top+300pt, start: parent.start+24pt}
        size: {w: 85%, h: 28%}
```

A locale block is optional until a locale is selected. Use explicit locales for multilingual work.

## 2. Rules and recipes

| Field | Rule |
|---|---|
| Canvas, font size, stroke width, letter spacing, stack gap/padding | Absolute `px`, `pt`, `mm`; bare numbers mean points. No `%` without a defined basis. |
| Constraint sizes | Absolute units, parent-relative `%`, `fill`, or text `fit_content`. Anchor offsets take absolute units, not `%`. |
| Mask, shape, effect length parameters | `px`, `pt`, `mm`; pixels convert using the canvas DPI. Bare numbers are points; `%` is rejected. |
| Text, image asset, colors, effect/shape params | Support `{{ expressions }}`; a whole expression preserves its value type. Mask params use literal values. |
| Numeric style fields, stack settings, fit sizes | Use literals, style roles, or format/locale patches. Numeric style expressions are rejected with an alternative. |
| Anchors | Logical `start`/`end` mirror in RTL; physical `left`/`right` stay fixed. |
| Stack children | Position comes from `hstack`/`vstack`; do not add anchors on the children. |
| Paragraphs | Use `paragraph.align` and `paragraph.direction`; no line-height control in this build. |

Let the engine wrap and fit a headline instead of splitting it into separately positioned lines:

The complete group recipe (replace or insert it with `template patch`):

```yaml
id: copy
type: group
layout: vstack
gap: 12pt
constraints:
  anchor: {top: parent.top+24pt, start: parent.start+24pt}
  size: {w: 80%, h: 50%}
children:
  - id: headline
    type: text
    text: "{{ title }}"
    style: {font: Inter, font_size: 48pt, color: "#111111"}
    fit: {policy: shrink_to_fit, min_size: 24pt, max_lines: 3}
    constraints: {size: {w: fill, h: fit_content}}
```

Draw wedges and triangles with a `path` node, e.g. `d: "M0 0 L120 0 L120 60 Z"`, a `style.fill`,
and explicit constraints. Path coordinates are points. Do not calculate rotated rectangle angles
for a shape the path language can express. For art direction, format design, or a missing effect,
read [art-direction.md](references/art-direction.md), [multi-format.md](references/multi-format.md),
or [extending.md](references/extending.md) only as needed.

## 3. Inspect → patch → validate → render → look → inspect layout

```bash
arcavex template patch templates/card --set nodes.title.style.font_size --value 48pt --json
arcavex template patch templates/card --set template.locales --value '{"en":{"direction":"ltr"}}' --json
arcavex validate templates/card -f square -l en --json
arcavex render templates/card -f square -l en --dpi 48 -o outputs/preview.png --json
arcavex layout inspect templates/card -f square -l en --json > outputs/layout.json
```

Look at the preview. View a reduced-DPI image first to conserve context; open the full render for
the final check. Use `render --debug` to see node IDs, bounds, baselines, and safe areas before
writing pixel-measurement scripts. Debug overlays belong to inspection output, not delivery.

Use JSON and filter it instead of loading a whole layout report:

```bash
jq '[.. | objects | select(.kind? == "text" and has("bounds_pt")) |
     {id, bounds_pt, paint_bounds_pt, overflow}]' outputs/layout.json
```

`layout inspect` reports transformed geometry and separates content collisions from effect spill.
A rotated node's bounds are an axis-aligned enclosure, not proof that every pixel intersects.
It compares siblings; examine pixels for collisions across groups. Clean validation alone does
not establish readable typography or good design. Use `explain ARC-... --json` for a diagnostic.

Edit by stable node IDs with `template patch`, never regex substitutions in YAML. Set/remove
metadata with `template.<section>[.<field>]`; split-template metadata lives in sidecar files and
must be edited there. Batch edits with `--ops-file`; stale source can be guarded by `--base-sha256`.
For an existing desktop project that needs undo/history or policy enforcement, use the semantic
`editor apply` transaction workflow in [engine-and-loop.md](references/engine-and-loop.md).

## 4. Series and verification

Keep one template and a folder of data files, with one render loop:

```bash
for data in data/*.yaml; do
  name=$(basename "$data" .yaml)
  arcavex render templates/card --data "$data" -f square -l en -o "outputs/$name.png" --json
done
```

For tracked campaigns, use `project new`, then project-mode `render`, `validate`, `preview`, and
`layout inspect` (omit the template argument). Choose a single format and locale for layout
inspection. `batch 'campaigns/*'` renders project directories; it is not CSV row rendering.
The generated [commands.md](references/commands.md) lists only commands this CLI implements.

Verify every required format × locale × realistic content profile: longest headline, optional
fields omitted, RTL digits, transparency and crops. Inspect overflow, collisions, margins,
contrast against the real backdrop, missing glyphs, and hierarchy. Use a recorded render and
`rerun --check` to check identical bytes. See [verification.md](references/verification.md).

If an independent reviewer is available and authorized, request that pass. If it cannot run,
complete the same fixed checklist yourself and say the independent pass did not run. Do not
claim a second review occurred. Deliver the renders, editable template, data, assets, fonts/style
references, and a short statement of the formats/locales/content limits actually verified.

## MCP appendix

When only MCP is available, use `arcavex_template_inspect`, `arcavex_template_patch`,
`arcavex_template_validate`, `arcavex_render_preview`, and `arcavex_layout_inspect` for the same
loop. Preview returns an image. CLI-only capabilities such as installing fonts and authoring
extensions require a shell. Report a missing capability early.

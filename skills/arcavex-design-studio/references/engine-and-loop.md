# Engine, surfaces, and the authoring loop

## CLI setup and command reference

Use the build check and one-time setup in SKILL.md. The CLI is the primary surface; see
[commands.md](commands.md) for its generated command reference. Use the running executable's
`--help` if this skill and that executable have different identities. Project-local
`.arcavex-home` discovery follows the working directory; an explicit `ARCAVEX_HOME` wins.

## Windows

- Git Bash `/tmp` and Windows `C:\tmp` are different folders; pass the engine absolute Windows
  paths with forward slashes (`C:/work/out.png`), which every shell and the engine accept.
- Python printing non-ASCII on a cp1252 console raises `UnicodeEncodeError`: set
  `PYTHONIOENCODING=utf-8` (and `PYTHONUTF8=1`) or run `python -X utf8`.
- In Git Bash, `2>nul` creates a file named `nul`; use `2>/dev/null`. In cmd and PowerShell `nul`
  is the null device.
- Open a file for the user with `start "" "C:/path/file.png"` (cmd), `Start-Process` (PowerShell)
  or `os.startfile(path)` (Python); `cmd /c start file` fails on paths with spaces because the
  first quoted argument is taken as the window title.
- PowerShell sets variables with `$env:NAME = 'value'`; `NAME=value cmd` is bash-only.

## The loop

```
template inspect → patch → validate → preview (LOOK) → layout inspect → revise → render
```

Two failure modes to avoid:

- **Imagining the output.** Run the command and read what it says.
- **Stopping at green.** `validate` proves well-formedness. Only pixels show composition, and only
  `layout inspect` shows overflow and collisions.

## Reading diagnostics

Every diagnostic is a coded, located error with a fix hint — not free text. `explain <code>` gives
the full entry for any code you do not recognize. Trust the hint: it names the field and the scope.

Unknown fields are **rejected**, in every authoring scope. If you invent a plausible property, you
get a located error naming the real home for it — there is no per-node `condition:`, `opacity`
belongs in `style`, `width`/`height` in `constraints.size`. This is deliberate: an invented field
that silently did nothing would be far worse.

## Changing a design that already exists

Everything above builds a template. To *change* one — which is what a person at the desktop and an
assistant over MCP are both doing — use the semantic editor rather than patching source. One
transaction applies wholly or not at all, checks the project revision so it cannot overwrite work
done since you last looked, writes atomically, and is undoable.

```
{"command_id": "<uuid4>",
 "project_path": "<absolute path to the project directory>",
 "base_project_revision": "<project_revision from project_snapshot>",
 "actor": {"id": "<who is editing>"},
 "target": {"format": "<name>", "locale": "<name or null>"},   # optional
 "commands": [{"kind": "<one of the kinds below>", ...}]}
```

Command kinds and their required fields. **Geometry is in points (`_pt`) whatever units the
template is authored in:**

```
set_text          layer_id, text
set_property      layer_id, keypath, value            (or remove: true)
set_visibility    layer_id, visible
set_display_name  layer_id, display_name              (writes project.ui.yaml, not the template)
translate         layer_ids, dx_pt, dy_pt
resize            layer_id, w_pt and/or h_pt
rotate            layer_id, deg
reorder           layer_id, parent_id, index
reparent          layer_id, parent_id, index
duplicate         layer_id
delete            layer_ids
group             layer_ids, group_id
splice_children   layer_id, children
set_effects       layer_id, effects
```

Submit an empty transaction and the engine states the whole shape back, every command kind
included — the fastest way to check the contract without guessing.

`editor_undo` / `_redo` / `_history` work on a history stored beside the project and shared with
every other client, so undo reverses the newest transaction *whoever made it*.

**Prefer this to `template_patch` for anything you may want to undo.** Patching writes source
directly, moving the project to a revision the chain has not seen: the records survive but stop
applying, and `editor_history` reports `branched_by_external_edit`. `set_property` reaches any node
field, so the editor covers what patching does.

Two traps worth one line each:

- `paragraph.align` overrides `style.align`; edit the paragraph when an explicit paragraph
  setting is present. With no paragraph override, the style value supplies the default.
- Sizes carry units (`70px`, `24pt`). Rewriting `70px` as a bare `70` silently changes it.

## Reading a change back

`layer_tree` in `rendered` mode reports `text` (what is authored, `{{ headline }}`) *and*
`resolved_text` (what it became for this format and locale). Check a wording change with that
rather than rendering a full-size image and looking at it. It also reports each node's authored
`style` and `paragraph` mappings, so you can see a value before you change it.

## Field notes

These are traps that cost real sessions iterations. Each names the builds it applies to; re-check
after an engine update.

- **Variable-height blocks.** Use a `layout: vstack` group with `gap` and children sized
  `h: fit_content`; never fixed-height boxes sized for the longest copy (short copy leaves a hole
  under it). Without a stack, chain siblings: `anchor: {top: <sibling-id>.bottom+16px}` plus
  `h: fit_content`. Ignore engine hints that say stacks "arrive in Phase 2": they are stale.
  Applies to: every build checked (old standalone 0.1.0 and `fd1496c`).
- **Silent shrink.** `fit: {policy: shrink_to_fit}` reduces the font until the text fits the box
  and `validate` stays clean with no warning, so the same headline can render at three sizes
  across formats. `layout inspect` shows it: the node's `overflow` is non-null with
  `kind: shrunk` and `measured_*`/`box_*` sizes. Size the box to the real line height times the
  line count (next trap), and check every text node's `overflow` before calling a size final.
  <!-- TODO(A3): document the strict mode / shrink warning once merged -->
  Applies to: every build checked.
- **Line breaks.** A real newline character breaks the line: YAML double quotes `"First\nSecond"`,
  a `|` block, or JSON `"\n"`. A backslash-n inside a plain or single-quoted YAML scalar is two
  literal characters and prints as `\n`. There is no balanced-wrap option; control wrapping with
  box width.
  <!-- TODO(A4): document wrap: balance / newline handling once merged -->
  Applies to: every build checked.
- **Patch order.** Root node values are the base every format patches. In a format's or locale's
  `patch:` list a later `set` on the same path wins, so a property set only in an earlier
  duplicate block is easy to lose and the node silently falls back to the root value. Keep one
  `patch:` list per format and list every property that format changes.
  `template patch --set nodes.<id>...` edits root fields only; to change a format's list, read it
  with `template inspect --json`, then replace the whole list:
  `arcavex template patch T --set template.formats.<name>.patch --value '<full JSON list>' --json`
  (same for `template.locales.<name>.patch`). Entry-level paths such as `...patch.0.value` are
  rejected (`ARC-TPL-092`).
  <!-- TODO(A5): document format-addressable template patch once merged -->
  Applies to: every build checked.
- **Line height.** There is no line-height control; the font's own metrics decide it. Measure a
  family once: put one line of text in a box with `h: fit_content`, run `layout inspect`, and
  divide the node's `bounds_pt` height (4th value; bounds are `[x, y, w, h]`) by the font size.
  Measured examples: Inter ≈ 1.21, Vazirmatn ≈ 1.56, Archivo Black ≈ 1.30. A box for N lines needs
  about N x size x factor.
  <!-- TODO(A6): replace with font metrics command once merged -->
  Applies to: every build checked.
- **Font family names.** Use the family `font add --json` or `font list` reports, never a filename.
  Builds before `3a4607d` on Windows dropped weight words from some families (`Archivo Black`
  registered as `Archivo`); when reproducing such a pin, map it in the locale:
  `fonts: {"Archivo Black": Archivo}` instead of guessing names.
  Applies to: Windows builds before `3a4607d`.
- **Angled edges.** Bounds are axis-aligned boxes, so a rotated band, wedge or diagonal seam cannot
  be checked from `layout inspect` numbers. Measure the rendered PNG instead: scan the pixel column
  at the element's x for the colour transition, read the seam's y there, and keep the element clear
  of it. Applies to: every build (geometry, not a bug).
- **Noisy overlap list.** `layout inspect` lists every sibling overlap, including intentional
  layering (backgrounds, textures, photos under text). Filter for signal: overlaps with
  `kind: content` where both nodes are text, plus every node with a non-null `overflow`. It
  compares siblings only (never across groups), so check cross-group collisions in pixels. This
  filter needs only Python, since `jq` is often missing on Windows:
  ```bash
  python -c "import json,sys; d=json.load(open(sys.argv[1])); t=set(); s=[d['root']]
  while s:
      n=s.pop(); s+=n['children']
      if n['kind']=='text': t.add(n['id'])
      if n.get('overflow'): print('overflow', n['id'], n['overflow']['kind'])
  [print('overlap', o['a'], o['b']) for o in d['overlaps'] if o['kind']=='content' and {o['a'], o['b']} <= t]" outputs/layout.json
  ```
  <!-- TODO(A8): document layout inspect filters once merged -->
  Applies to: every build checked; the `content`/`halo` classification needs `8aaa162` (2026-08) or
  later.

## Context cost

`layout inspect --json` on a real poster is tens of thousands of characters. Do not page the whole
thing into context for every iteration — inspect one format at a time, save the JSON to a file, and filter only the relevant nodes.

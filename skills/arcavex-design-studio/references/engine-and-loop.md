# Engine, surfaces, and the authoring loop

## Finding the engine

Try in order, and say which one you got:

```bash
arcavex --version                      # installed on PATH
python -m arcavex.clients.cli --version # installed, script not on PATH
arcavex doctor                          # confirms skia, ICU, fonts, exporters
```

`doctor` is the fastest way to learn what this machine can actually do. Run it once before
committing to a direction — a missing font family or exporter changes what you should design.

If nothing works, the user installs with `pip install arcavex` (or `uv pip install arcavex`), then
`arcavex skill install` to refresh this skill.

## Isolate your workspace

Point `ARCAVEX_HOME` at a task-local directory so added fonts, enabled extensions, and caches never
mutate the user's global engine:

```bash
export ARCAVEX_HOME="$PWD/.arcavex-home"    # PowerShell: $env:ARCAVEX_HOME = "$PWD/.arcavex-home"
```

Everything you install — fonts, extensions — then lives with the campaign and travels with it.

## Command ↔ MCP tool map

| Task | CLI | MCP |
|---|---|---|
| Read a template's contract and node ids | `template inspect --json` | `arcavex_template_inspect` |
| Edit an addressed node | `template patch` | `arcavex_template_patch` |
| Check it compiles | `validate --format F` | `arcavex_template_validate` |
| **See the image** | `render --format F -o out.png` | `arcavex_render_preview` |
| Resolved geometry, overlaps, overflow | `layout inspect --format F` | `arcavex_layout_inspect` |
| Vocabulary | `effects list`, `style list`, `font list` | `arcavex_effects_list`, `arcavex_style_list`, `arcavex_font_list` |
| Explain a diagnostic code | `explain ARC-…` | `arcavex_diagnostic_explain` |
| Recorded, reproducible render | `project render` | `arcavex_project_render` |
| Author an effect | `ext scaffold/validate/test/add/enable` | **not exposed — shell only** |
| Install a font | `font add PATH` | **not exposed — shell only** |

`arcavex_render_preview` returns the image itself, so you can look at it. On the CLI, render to a
file and read that file.

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

- Alignment is `paragraph.align`, not `style.align`. The schema accepts both; the text renderer
  reads only `paragraph`, so a value written to `style.align` is stored and never applied.
- Sizes carry units (`70px`, `24pt`). Rewriting `70px` as a bare `70` silently changes it.

## Reading a change back

`layer_tree` in `rendered` mode reports `text` (what is authored, `{{ headline }}`) *and*
`resolved_text` (what it became for this format and locale). Check a wording change with that
rather than rendering a full-size image and looking at it. It also reports each node's authored
`style` and `paragraph` mappings, so you can see a value before you change it.

## Context cost

`layout inspect --json` on a real poster is tens of thousands of characters. Do not page the whole
thing into context for every iteration — read the human output, or inspect one format at a time, and
reach for `--json` when you need to filter precisely.

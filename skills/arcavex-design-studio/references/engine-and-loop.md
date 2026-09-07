# Engine, surfaces, and the authoring loop

## Finding the engine

Try in order, and say which one you got:

```bash
arcavex --version                        # installed on PATH
python -m arcavex --version              # installed, scripts directory not on PATH
python -m arcavex.clients.cli --version  # the same, on an older engine
arcavex doctor                           # confirms skia, ICU, fonts, exporters
```

`doctor` is the fastest way to learn what this machine can actually do. Run it once before
committing to a direction — a missing font family or exporter changes what you should design.

**Arcavex Desktop carries its own engine.** The Windows build (the only packaged platform so far)
ships a standalone `arcavex.exe` in an `engine/` folder beside the application executable and
launches it as `arcavex mcp serve`; in a source checkout the same file sits at
`apps/desktop/src-tauri/binaries/engine/arcavex.exe`. It is the full CLI, so if nothing is on PATH
but the app is installed, run that file directly. A developer build points the app at any engine
with `ARCAVEX_DESKTOP_ENGINE=<path>`.

## Installing

Arcavex is not on PyPI yet — that comes with the first release — so `pip install arcavex` will not
get you this engine. The person installs it as a global command with uv, which fetches a Python if
the machine has none:

```bash
uv tool install git+https://github.com/payam-ranjbar/arcavex   # global `arcavex` command, no venv
uv tool install /path/to/arcavex                                # or from a clone
arcavex doctor                                                  # confirms skia, ICU, fonts, exporters
arcavex skill install                                           # refresh this skill in the host
```

## Connecting

The MCP server is `arcavex mcp serve`: MCP over stdio, no network. Register it with the host:

```bash
arcavex mcp install            # Claude Code (user scope), Claude Desktop, or Codex
arcavex mcp install --print    # print the snippet for hand-editing any other host's config
```

The host reads its configuration at start-up, so it needs a restart or a new session afterwards;
then `arcavex_effects_list` proves the connection. The command reference is the repository's
`docs/cli.md#mcp`.

**Arcavex Desktop** is the person's own window on the project: a viewer and editor for the same
project files, with no shell involved. It is not something you connect to — you edit over CLI or
MCP, and the window follows the files. It is not yet distributed as an installer.

## Isolate your workspace

Point `ARCAVEX_HOME` at a task-local directory so added fonts, enabled extensions, and caches never
mutate the user's global engine:

```bash
export ARCAVEX_HOME="$PWD/.arcavex-home"    # PowerShell: $env:ARCAVEX_HOME = "$PWD/.arcavex-home"
```

Everything you install — fonts, extensions — then lives with the campaign and travels with it.

## Command ↔ MCP tool map

Everything an assistant needs is reachable over MCP alone, from an empty directory to a recorded
run. What stays shell-only is extension authoring, font installation, and image preprocessing.

| Task | CLI | MCP |
|---|---|---|
| Start a template from nothing | `arcavex template new DIR` | `arcavex_template_new` |
| The library: publish, list, take a copy back | `arcavex template publish`, `arcavex template detach` | `arcavex_template_publish`, `arcavex_template_list`, `arcavex_template_detach` |
| Create a project around a template | `arcavex project new` | `arcavex_project_create` |
| Projects: status, list, clone | `arcavex status`, `arcavex project clone` | `arcavex_project_status`, `arcavex_project_list`, `arcavex_project_clone` |
| Write a project's content | `arcavex data set`, `arcavex data import` | `arcavex_data_set`, `arcavex_data_import` |
| Bring in an image, then describe it | `arcavex asset add`, `arcavex asset annotate` | `arcavex_asset_add`, `arcavex_asset_annotate` |
| Read a template's contract and node ids | `arcavex template inspect --json` | `arcavex_template_inspect` |
| Edit an addressed node (writes source) | `arcavex template patch` | `arcavex_template_patch` |
| Edit with undo (a semantic transaction) | `arcavex editor apply FILE`; `arcavex editor undo`, `arcavex editor redo`, `arcavex editor history` | `arcavex_editor_apply`; `arcavex_editor_undo`, `arcavex_editor_redo`, `arcavex_editor_history` |
| Check it compiles | `arcavex validate --format F` | `arcavex_template_validate` |
| **See the image** | `arcavex preview --format F` (add `--watch` to keep it live) | `arcavex_render_preview` (pass `dpi=96` while iterating) |
| Resolved geometry, overlaps, overflow | `arcavex layout inspect --format F` | `arcavex_layout_inspect` |
| The final file | `arcavex render TEMPLATE --format F -o out.png` | `arcavex_render` |
| Recorded direct render (template + data, with a run manifest) | `arcavex render --record` | `arcavex_render_record` |
| Recorded, reproducible render of a project | `arcavex render` inside the project, or `arcavex render --project DIR` | `arcavex_project_render` |
| Recorded runs: list, compare, repeat | `arcavex list-runs`, `arcavex diff`, `arcavex rerun` | `arcavex_run_list`, `arcavex_run_diff`, `arcavex_run_rerun` |
| Vocabulary | `arcavex effects list`, `arcavex shapes list`, `arcavex style list`, `arcavex style inspect`, `arcavex font list` | `arcavex_effects_list`, `arcavex_shape_list`, `arcavex_style_list`, `arcavex_style_inspect`, `arcavex_font_list` |
| Explain a diagnostic code | `arcavex explain ARC-…` | `arcavex_diagnostic_explain` |
| Author an effect | `arcavex ext scaffold`, `arcavex ext validate`, `arcavex ext test`, `arcavex ext add`, `arcavex ext enable` | **not exposed — shell only** |
| Install a font | `arcavex font add PATH` | **not exposed — shell only** |
| Preprocess an image (crop, trim alpha, remove a background) | your own tools, then `arcavex asset add` | **shell only** |

Tools without the `arcavex_` prefix (`project_snapshot`, `layer_tree`, `hit_test`, and the policy and
proposal tools) serve Arcavex Desktop's live view. You may call them, but authoring never needs them.

`arcavex_render_preview` returns the image itself, so you can look at it. On the CLI, preview or
render to a file and read that file.

## The loop

```
template inspect → edit (editor apply, or template patch) → validate → preview (LOOK) → layout inspect → revise → render
```

Two failure modes to avoid:

- **Imagining the output.** Run the command and read what it says.
- **Stopping at green.** `validate` proves well-formedness. Only pixels show composition, and only
  `layout inspect` shows overflow and collisions.

## Live view while you iterate

`arcavex preview TEMPLATE --format F --watch` re-renders to one stable path under
`$ARCAVEX_HOME/cache/preview/` on every save of the template or a file it depends on, printing
`changed=<file> … -> <path>` each time. Start it, open the printed path for the person (the file
name never changes, so their image viewer follows), then edit. Every separate CLI call pays about a
second of interpreter start-up before it does anything, so iterate through `--watch` or over MCP
rather than one `arcavex render` per change; `arcavex render` is for the final file.

## Reading diagnostics

Every diagnostic is a coded, located error with a fix hint — not free text. `arcavex explain <code>`
(MCP: `arcavex_diagnostic_explain`) gives the full entry for any code you do not recognize. Trust the
hint: it names the field and the scope.

Unknown fields are **rejected**, in every authoring scope. If you invent a plausible property, you
get a located error naming the real home for it — there is no per-node `condition:`, `opacity`
belongs in `style`, `width`/`height` in `constraints.size`. This is deliberate: an invented field
that silently did nothing would be far worse.

## Changing a design that already exists

Everything above builds a template. To *change* one — which is what a person at the desktop and an
assistant over MCP are both doing — use the semantic editor rather than patching source. One
transaction applies wholly or not at all, checks the project revision so it cannot overwrite work
done since you last looked, writes atomically, and is undoable. Submit it via `arcavex_editor_apply`
(CLI: `arcavex editor apply FILE`, where the file holds the JSON below):

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
rotate            layer_id, degrees
reorder           layer_id, parent_id, index
reparent          layer_id, parent_id, index
duplicate         layer_id
delete            layer_ids
group             layer_ids, group_id
splice_children   parent_id, index, remove_count, entries   (see the note below)
set_effects       layer_id, effects
```

Submit an empty transaction and the engine states the whole shape back, every command kind
included — the fastest way to check the contract without guessing.

`splice_children` is the engine's own restoration primitive: it is what an `undo` of a `delete`
or a `group` replays, and its `entries` are raw authored node mappings rather than semantic
intent. It does work for **adding** a node — the new node lands in the template and in the undo
history like any other edit — but you are composing authored YAML by hand, so validate and
preview straight after. For a node that does not exist yet, `arcavex_template_patch` with an
`insert_after` op is usually the clearer route; note that patching source is outside the editor's
history, so do it before the edits you want to be able to undo.

`arcavex_editor_undo`, `arcavex_editor_redo`, and `arcavex_editor_history` (CLI: `arcavex editor
undo`, `arcavex editor redo`, `arcavex editor history`) work on a history stored beside the project
and shared with every other client, so undo reverses the newest transaction *whoever made it*.

**Prefer this to `arcavex_template_patch` for anything you may want to undo.** Patching writes
source directly, moving the project to a revision the chain has not seen: the records survive but
stop applying, and `arcavex_editor_history` reports `branched_by_external_edit`. `set_property`
reaches any node field, so the editor covers what patching does.

Two traps worth one line each:

- Alignment: write `paragraph.align`. It is the primary field and wins when both are set;
  `style.align` is honoured as a fallback when `paragraph.align` is absent, and the two render
  byte-identically, but keep the value where the text renderer looks first.
- Sizes carry units (`70px`, `24pt`). Rewriting `70px` as a bare `70` silently changes it.

## Reading a change back

`layer_tree` in `rendered` mode reports `text` (what is authored, `{{ headline }}`) *and*
`resolved_text` (what it became for this format and locale). Check a wording change with that
rather than rendering a full-size image and looking at it. It also reports each node's authored
`style` and `paragraph` mappings, so you can see a value before you change it.

## Putting the result in front of the person

`arcavex_render_preview` shows the image to *you*; the person sees nothing until you hand them a
file. When a render is done, open it for them and state its absolute path:

```bash
start out.png        # Windows (cmd); PowerShell: Invoke-Item out.png
open out.png         # macOS
xdg-open out.png     # Linux
```

If Arcavex Desktop is open on the project, say so: it watches the project files and re-renders as
they change, so the window is already showing the result, and it labels edits it did not make as
coming from an external editor or AI client.

## Context cost

`arcavex layout inspect --json` on a real poster is tens of thousands of characters. Do not page
the whole thing into context for every iteration — read the human output, or inspect one format at
a time, and reach for `--json` when you need to filter precisely.

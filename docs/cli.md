# CLI reference

Every Arcavex capability is a subcommand of the `arcavex` executable. This page is the
command-by-command reference; the synopses and flags below are taken from the real
`arcavex … --help` output. For the authoring vocabulary the commands operate on (nodes,
constraints, expressions, locales, patches) see [template-schema.md](template-schema.md); for the
diagnostic codes any command can emit see [diagnostics.md](diagnostics.md).

```console
$ arcavex --version
arcavex 0.1.0
```

## Conventions

- **Global flags.** Every command accepts `--json` (machine-readable, versioned output — the human
  table/line is never printed alongside it), `--no-color`, and `--quiet` (suppress the human
  diagnostics/line only). `--json` output always carries a `response_version` integer.
- **Exit codes.** `0` success (warnings included), `1` validation/authoring error, `2` invalid CLI
  usage, `3` missing template/asset/font, `4` resource budget exceeded, `5` internal failure
  (`ARC-INT-999`). See [diagnostics.md](diagnostics.md#exit-codes).
- **Direct mode vs project mode.** `render`, `validate`, and `preview` take an optional `TEMPLATE`
  argument. With it, they operate on that file (direct mode). Without it, they discover the current
  project by walking upward for a `project.yaml` (project mode); `--project PATH` overrides
  discovery. There is no persistent "open project" state.
- **Format selection on output.** `render -o OUT` picks the exporter from the extension:
  `.png`, `.jpg`/`.jpeg`, `.webp`, or `.pdf`. With no `-o`, a deterministic default name
  `<template-stem>.<format>[.<locale>].png` is written in the current directory and reported first.

## Command index

| Command | One line |
|---|---|
| [`render`](#render) | Render a template (or the project) to an image or PDF. |
| [`validate`](#validate) | Validate without rendering. |
| [`preview`](#preview) | Render to a stable preview path; `--watch` re-renders on save. |
| [`doctor`](#doctor) | Check the environment and report the engine version. |
| [`explain`](#explain) | Explain a diagnostic code and its typical fix. |
| [`status`](#status) | Show the current project's manifest and recorded-run count. |
| [`list-runs`](#list-runs) | List recorded runs, newest first. |
| [`rerun`](#rerun) | Reproduce a recorded run into a new run directory. |
| [`diff`](#diff) | Diff two recorded runs (pixels + provenance). |
| [`batch`](#batch) | Render every matched project in parallel jobs. |
| [`template …`](#template) | Authoring: new/check/inspect/split/patch/publish/detach. |
| [`layout inspect`](#layout-inspect) | Report resolved geometry, anchors, overlaps. |
| [`style …`](#style) | List/inspect installed style packs. |
| [`effects …`](#effects) | List/inspect the registered effects. |
| [`font …`](#font) | List the available font families; install or remove a typeface. |
| [`project …`](#project) | Project lifecycle: new/clone/set-status/upgrade. |
| [`data …`](#data) | Project data authoring: set/import. |
| [`asset …`](#asset) | Asset ingest/annotation. |
| [`mcp …`](#mcp) | MCP authoring server: serve/tools; `install` registers it with an AI host. |
| [`ext …`](#ext) | Trusted local extension lifecycle. |
| [`editor …`](#editor) | Semantic project editing: apply a transaction, undo, redo, history. |
| [`skill install`](#skill) | Install the bundled design skill into an AI assistant. |
| [`desktop handshake`](#desktop) | What Arcavex Desktop checks before it trusts an engine. |

---

## render

Render a template to an image or PDF, or (no template) the current project's runs.

```
arcavex render [TEMPLATE] [OPTIONS]
```

| Flag | Meaning |
|---|---|
| `-d, --data PATH` | Data YAML file. |
| `-f, --format TEXT` | Format name (required if the template declares more than one). |
| `-l, --locale TEXT` | Apply a declared locale (direction, digits, fonts, data overlay, patch). |
| `--style TEXT` | Style pack (`name@version` or `./file.yaml`); overrides the template's `style:`. |
| `-o, --output PATH` | Output path; the extension selects the format. |
| `--project PATH` | Project directory (project mode); overrides discovery. |
| `--record` | Write a recorded-run manifest (direct mode; always on in project mode). |
| `--dpi INTEGER` | Override render DPI (highest-precedence layer, §6.3). |
| `--quality 1..100` | Lossy encoder quality (JPEG, lossy WebP; default 90). Ignored for PNG/PDF. |
| `--lossless` | Encode WebP losslessly (ignored for other formats). |
| `--debug` | Overlay node bounds, ids, baselines, and the safe-area margin. |

```console
$ arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square -o hello.png
Rendered hello.png
```

With no `-o`, the default name is reported before rendering (on failure too):

```console
$ arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square
inferred: output=hello-poster.square.png
Rendered hello-poster.square.png
```

## validate

Validate a template, or (with no template) the current project, without rendering.

```
arcavex validate [TEMPLATE] [OPTIONS]
```

Accepts `-d/--data`, `-f/--format`, `-l/--locale`, `--style`, `--project`. Exit `0` on success
(including warnings), `1` on a validation error.

## preview

Preview a template to a stable path (with `--watch`, keep re-rendering), or the project.

```
arcavex preview [TEMPLATE] [OPTIONS]
```

Adds `--watch` (re-render on every dependent-file save) and `--debug` to the render/validate flag
set. Writes to a stable preview path under `$ARCAVEX_HOME/cache/preview` so an external viewer can
watch one file. The path is keyed on the template plus every input that changes the pixels
(`--data`, `--locale`, `--dpi`, `--style`): the same command always lands on the same file, and two
variants previewed side by side get two files rather than taking turns overwriting one. The path is
printed first, whole, on its own line; the compile and render timings follow.

## doctor

Check the environment (Python, Skia, ICU, fonts, exporters, cache, temp dir, paths, config) and
report the engine version.

```console
$ arcavex doctor
Arcavex engine 0.1.0
┌───────────┬────────┬────────────────────────────────────────────────────────┐
│ check     │ status │ detail                                                 │
├───────────┼────────┼────────────────────────────────────────────────────────┤
│ python    │ ok     │ Python 3.12.13                                         │
│ skia      │ ok     │ skia-python 144.0.post2                                │
│ icu       │ ok     │ ICU available (skia.Unicode built)                     │
│ fonts     │ ok     │ 4 bundled families: Estedad, Inter, Lalezar, Vazirmatn │
│ exporters │ ok     │ png, jpeg, webp, pdf all available                     │
│ cache     │ ok     │ derived cache=…\.arcavex\cache\derived;                │
│           │        │ budget=256000000 bytes (disposable)                    │
│ temp_dir  │ ok     │ Writable temp dir: …\AppData\Local\Temp                │
│ paths     │ ok     │ home=…\.arcavex [default (~/.arcavex)];                 │
│           │        │ preview cache=…\.arcavex\cache\preview                  │
│ config    │ ok     │ config.toml absent (…\.arcavex\config.toml);           │
│           │        │ default dpi=per-format [default]                       │
└───────────┴────────┴────────────────────────────────────────────────────────┘
```

`doctor --json` emits the same report as versioned JSON. See [install.md](install.md#doctor) for
what each row proves and the ICU remediation path.

## explain

Explain a diagnostic code: what it means and the typical fix.

```console
$ arcavex explain ARC-TPL-014
ARC-TPL-014 — Required or referenced variable is missing
A variable is required but not provided, or an expression references a variable
that is neither declared nor supplied.
fix: Add the value to your data file, give the variable a default, or guard the
reference with '| default(...)'.
```

An unknown code exits `1`. The full catalog is [diagnostics.md](diagnostics.md).

## status

Show the current project's manifest and recorded-run count. Accepts `--project`.

## list-runs

List recorded runs (the project's, or with `--path` a direct-mode `outputs/` directory),
newest first. With no project and no `--path`, falls back to `./outputs`.

## rerun

```
arcavex rerun RUN_DIR
```

Reproduce a recorded run into a new run directory. On the same engine version and platform the
output is byte-identical; if a recorded input drifted on disk, `rerun` renders from the current
inputs and names the drift (`ARC-RUN-002`) rather than silently differing.

## diff

```
arcavex diff RUN_A RUN_B
```

Per-output pixel/perceptual diff plus separate template/data/asset/font/engine/option/override
change attribution.

## batch

```
arcavex batch PATTERNS... [-j/--jobs N] [--dpi N]
```

Render every project matched by the glob(s) across `N` parallel jobs; the output is byte-identical
to a serial run.

---

## template

Template authoring commands.

| Subcommand | Purpose |
|---|---|
| `new DIR` | Scaffold a minimal renderable template (`template.yaml` + `data.yaml` + README). |
| `check PATH [-f -l --style]` | Validate a template without data (schema + structure + `preview_data`). |
| `inspect PATH [--json] [--resolved -f -l]` | Report the authored contract; `--resolved` shows the resolved direction/digits and each applied patch with its originating layer. |
| `split PATH` | Convert a one-file template into a split directory, losslessly. |
| `patch PATH …` | Apply path-addressed `set`/`remove`/`insert_before`/`insert_after` ops to a template on disk (comment-preserving). The AI-mutation contract, also on the CLI. |
| `publish DIR --name N --version V [--no-default]` | Publish a template into the library as an immutable `N@V`. |
| `detach [--project P]` | Copy the project's library template into the project (disables version upgrades). |

```console
$ arcavex template new ./mytpl
Created ./mytpl (render with --format square)
```

```console
$ arcavex template inspect examples/hello-poster/template.yaml
variables (2):
  title: string (required) Main headline
  subtitle: string (optional) Supporting line under the title
formats: square, story
nodes:
  root: group
  background: shape
  accent: shape
  title: text
  subtitle: text
functions:
  contrast_color(color: string) -> string
  …
```

`template patch` takes one of `--set P --value V`, `--remove P`, `--insert-before P --node J`,
`--insert-after P --node J`, or `--ops-file F`, with an optional `--base-sha256 H` guard that
refuses the write if the file changed on disk since it was read (`ARC-TPL-110`).

## layout inspect

```
arcavex layout inspect TEMPLATE [-d -f -l] [--json]
```

Report resolved geometry: per-node bounds (pt + px), the anchor derivation for each axis, overflow,
and sibling overlaps — geometry a compile-clean `validate` cannot see.

Every node prints **two** boxes. `bounds` is the layout box the solver resolved. `paint` is that
box grown by the node's rotation and by the bounds expansion its effects declare, so the renderer
can allocate room for a blur or a tear. The two are equal unless the node is rotated or carries an
expanding effect.

```console
$ arcavex layout inspect examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square
canvas 810x810pt (1080x1080px @ 96dpi) format=square locale=-
root group bounds (0.0, 0.0, 810.0, 810.0)pt
  paint (0.0, 0.0, 810.0, 810.0)pt
  v: top = parent.top → 0.0pt
  h: left = parent.left → 0.0pt
  accent shape bounds (105.3, 226.8, 599.4, 356.4)pt
    paint (105.3, 226.8, 599.4, 356.4)pt
    h: center_x = parent.center_x → 405.0pt
  …
overlaps: 2 content, 0 effect spill
  accent ∩ title at (145.8, 352.5, 518.4, 69.0)pt
  accent ∩ subtitle at (145.8, 450.0, 518.4, 31.0)pt
coverage: 100% of canvas
```

Both of those are `content` overlaps and both are intentional — the text is meant to sit on the
accent panel. `layout inspect` reports geometry; deciding which intersections are by design is
still the author's call.

### Overlap kinds

Every overlap carries a `kind` naming what actually collided:

| `kind` | Condition | What to do |
|---|---|---|
| `content` | The nodes' layout `bounds` intersect. | A genuine collision. `rect_pt` is the colliding area itself, so its width or height is the correction to apply. |
| `halo` | Only the effect-grown `paint` boxes intersect. | Effect spill: one node's shadow, glow or torn-paper amplitude reaches over its neighbour. Usually the intended look. |

Human output lists `content` overlaps first and demotes `halo` ones into a dimmed *effect spill*
subsection. For a poster whose `strip` casts a drop-shadow across a 10pt gap to `tag`, while
`venue-2` genuinely bites 4pt into `venue-1`:

```
overlaps: 1 content, 1 effect spill
  venue-1 ∩ venue-2 at (20.0, 236.0, 200.0, 4.0)pt
  effect spill (paint bounds only — usually intended):
    strip ∩ tag at (130.0, 20.0, 50.0, 40.0)pt
```

`--json` and the `arcavex_layout_inspect` MCP tool carry `kind` on every overlap, so an agent
filters on it directly rather than re-deriving the distinction from geometry:

```console
$ arcavex layout inspect examples/hello-poster/template.yaml --format square --json \
  | jq '[.overlaps[] | select(.kind == "content")]'
```

A rotated node contributes its axis-aligned bounding box, not its rotated outline. Two rotated
nodes that visually clear each other can therefore still report a `content` overlap; the per-node
`paint` box is what makes that arithmetic checkable by hand.

Full-bleed backdrops and groups that enclose their siblings are suppressed rather than reported —
containment by a node covering ≥90% of its parent region, or by a group, is structure, not a
collision. A node's shadow cannot buy it that exemption: the threshold is measured on the layout
box, not the paint box.

**Pairs are enumerated within each group.** Two nodes in different groups are never compared, so
an empty `overlaps` list means no sibling collisions, not that nothing on the canvas collides —
on the reference poster, 20-22 intersecting cross-group pairs go unreported per format. For a
whole-canvas check, compare `bounds_pt` across the tree from `--json`. The reasoning and the
measured trade-off are in
[known-limitations.md](known-limitations.md#overlap-reporting-is-per-group).

## style

| Subcommand | Purpose |
|---|---|
| `list [--json]` | List installed style packs (palettes, presets, roles). |
| `inspect NAME [--json]` | Show a pack's palettes, fonts, effect presets, and role defaults. |

```console
$ arcavex style list
pop-art@0.1.0 palettes=5 presets=4 roles=3
```

## effects

| Subcommand | Purpose |
|---|---|
| `list [--json]` | List registered effects, their category, and each param's type/default/range. |
| `inspect NAME [--json]` | Show one effect's category and full parameter schema. |

```console
$ arcavex effects list
blur raster
  radius: length (default=4.0) [>=0]
drop-shadow composite
  dx: length (default=6.0)
  dy: length (default=8.0)
  blur: length (default=4.0) [>=0]
  color: colour (default=[0.0, 0.0, 0.0, 0.45])
  …
```

The full effect list and its usage notes are in
[template-schema.md](template-schema.md#effects).

## font

Font install/inspect commands (spec §4.3). Rendering is confined to the families listed here —
system fonts are **never** consulted, because determinism requires it — so any typeface beyond the
four bundled families must be installed before a template may name it.

| Subcommand | Purpose |
|---|---|
| `list [--json]` | List every resolvable family, its files, and whether it is bundled or installed; names the install directory. |
| `add PATH [--license PATH]` | Install a `.ttf` into `$ARCAVEX_HOME/fonts` and report the family name templates must use. |
| `remove FAMILY [--json]` | Remove an installed family. A family bundled with the engine is refused (`ARC-RND-032`). |

```console
$ arcavex font list
Estedad bundled (3 file(s))
  Estedad-Black.ttf
  Estedad-Bold.ttf
  Estedad-Regular.ttf
Inter bundled (5 file(s))
  Inter-Black.ttf
  …
Lalezar bundled (1 file(s))
  Lalezar-Regular.ttf
Vazirmatn bundled (5 file(s))
  …
install fonts into: C:\Users\you\.arcavex\fonts
add one with: arcavex font add <path/to/font.ttf>
```

`add` reports the family name **as the engine resolves it**, read from the file itself. A file stem
and its internal family name routinely differ, and `style.font` must name the *family*, so this is
the name to write — never the filename:

```console
$ arcavex font add ~/Downloads/MyFace.ttf
Installed Lalezar into C:\Users\you\.arcavex\fonts
  use it in a template as: style: {font: Lalezar}
```

A family that ships with the engine cannot be removed — it backs the default font stacks, and the
files would return on the next reinstall:

```console
$ arcavex font remove Inter
ERROR ARC-RND-032 Font family 'Inter' is bundled with the engine and cannot be removed
  hint: Bundled families ship with Arcavex; only families added with 'arcavex font add' can be removed.
```

`--license PATH` copies a licence file alongside the font as `LICENSE-<family>-<name>`, the
convention the bundled OFL licences follow; `remove` deletes it with the family. Naming a family
that is not available is [`ARC-RND-010`](diagnostics/ARC-RND-010.md), whose hint lists the nearest
available families and points at `arcavex font add`.

## project

Project lifecycle commands (spec §5).

| Subcommand | Purpose |
|---|---|
| `new DIR --template REF [--name N] [--style S] [-f F …] [-l L …]` | Scaffold a project pinning a template (`name@version` or a path). |
| `clone DIR [--name N] [--project P]` | Clone a project into a new directory, reset to draft, dropping recorded runs. |
| `set-status STATUS [--project P]` | Set the status (`draft`/`review`/`approved`/`published`). |
| `upgrade --to V [--yes] [--project P]` | Preview a template-version upgrade (structural stale paths + perceptual diff); `--yes` updates the pin. |

## data

Project data authoring commands (spec §3.7).

| Subcommand | Purpose |
|---|---|
| `set KEYPATH VALUE [--project P]` | Set a single value (VALUE parsed as JSON, else a string), then revalidate. |
| `import [FILE] [-l L] [--project P]` | Merge a YAML data document (or stdin) under overlay semantics. |

A key matching no declared variable warns with `ARC-TPL-112`. The report reflects compile-time data
validation, not the layout pass (see [known-limitations.md](known-limitations.md)).

## asset

Asset ingest/annotation commands (spec §4.7).

| Subcommand | Purpose |
|---|---|
| `add SOURCE [--project P]` | Ingest an image into the content-addressed store and report its reference. |
| `annotate SHA256 [--set k=v … \| --annotations J]` | Write sidecar annotations (facing/focal_point/tags). |

## mcp

MCP authoring server (spec §6.2).

| Subcommand | Purpose |
|---|---|
| `serve` | Start the stdio MCP authoring server (blocks until the client disconnects). |
| `tools [--json]` | Print the tool catalog (names, descriptions, input/output schemas). |
| `install [--target T …] [--list] [--print] [--force] [--command PATH]` | Register the server with every AI host present on this machine, or the named ones: `claude-code`, `claude-desktop`, `codex` (`desktop` and `chatgpt` are aliases). `--list` shows each host's state without writing; `--print` shows the snippet to paste by hand; `--force` replaces an existing `arcavex` entry; `--command` registers another executable. |

Every MCP tool is a thin wrapper over one facade method and returns the same versioned pydantic
result as the CLI's `--json`. See [architecture.md](architecture.md#mcp-parity) and the
[MCP section of the README](../README.md#mcp-authoring-surface-62).

### Connecting a host

`mcp install` registers the server with the assistants on this machine, so nobody has to find a
config file and type an absolute path into it. It knows three hosts. Claude Code is registered
through `claude mcp add` at user scope — the scope that works in every project without an approval
prompt — and its own file is never edited. Claude Desktop has no CLI, so its
`claude_desktop_config.json` is edited in place: every other key is kept, the file's indentation
too, the write is atomic, and the previous content stays beside it as `.bak`. Codex goes through
`codex mcp add` when the CLI is on PATH and otherwise gets a `[mcp_servers.arcavex]` table in
`~/.codex/config.toml`, appended (or, with `--force`, swapped) by text so nothing else in the file
is reformatted. A host that is not installed is skipped with a notice; with no `--target`, `ok`
means every host that is here has been registered.

```console
$ arcavex mcp install --list
target          location                                                        state
Claude Code     claude mcp (user scope)                                         registered
Claude Desktop  C:\Users\you\AppData\Roaming\Claude\claude_desktop_config.json  not registered
Codex CLI       C:\Users\you\.codex\config.toml                                host not found
command: C:\Users\you\arcavex\.venv\Scripts\arcavex.exe mcp serve
```

The command registered is the engine that ran `mcp install`: the frozen executable, or the
`arcavex` console script beside the running interpreter, or `python -m arcavex` — always as
absolute paths, and always printed so you can see exactly what a host will run. `--command PATH`
registers that executable instead (as `PATH mcp serve`).

`--print` writes nothing and prints, per host, exactly what a person would paste to do it by hand.
The same snippet is in the hint when a host named with `--target` is not installed
(`ARC-MCP-002`).

```console
$ arcavex mcp install --print
Claude Code  claude mcp (user scope)
Registered for every project; 'claude mcp list' shows it under user scope.
claude mcp add -s user arcavex -- C:\Users\you\arcavex\.venv\Scripts\arcavex.exe mcp serve

Claude Desktop  C:\Users\you\AppData\Roaming\Claude\claude_desktop_config.json
Quit and reopen Claude Desktop after registering; it reads the file at start.
{
  "mcpServers": {
    "arcavex": {
      "command": "C:\\Users\\you\\arcavex\\.venv\\Scripts\\arcavex.exe",
      "args": [
        "mcp",
        "serve"
      ]
    }
  }
}

Codex CLI  C:\Users\you\.codex\config.toml
The ChatGPT desktop app cannot run a local MCP server; Codex is the OpenAI host that can.
[mcp_servers.arcavex]
command = "C:\\Users\\you\\arcavex\\.venv\\Scripts\\arcavex.exe"
args = ["mcp", "serve"]

command: C:\Users\you\arcavex\.venv\Scripts\arcavex.exe mcp serve
```

An existing `arcavex` entry is refused with `ARC-MCP-003`; `--force` replaces it. Each host reads
its configuration when it starts: open a new Claude Code session, quit and reopen Claude Desktop,
start a new Codex session. The plain-language walkthrough for someone setting up an assistant is
[connect-your-assistant.md](connect-your-assistant.md).

## editor

Semantic project editing: the same transactions Arcavex Desktop submits, from the command line.
A transaction names the project revision it was composed against and is applied atomically; a
conflict or a refused command writes nothing and reports why. The model, the command kinds, and
every refusal are in [desktop/editor.md](desktop/editor.md).

| Subcommand | Purpose |
|---|---|
| `apply FILE [--project P]` | Execute one semantic transaction (JSON); a refusal reports conflicts or diagnostics. |
| `undo [--project P]` | Restore the project state before its newest applied history entry. |
| `redo [--project P]` | Re-apply the oldest undone history entry. |
| `history [--project P]` | Show the undo/redo timeline and whether an external edit branched it. |

## skill

Install the bundled design skill — the document that teaches an AI assistant this engine's
authoring loop, art direction, multi-format and locale work, and verification — into the
assistant's own skill directory.

| Subcommand | Purpose |
|---|---|
| `install [--target T …] [--path DIR] [--project] [--force] [--list]` | Copy the skill to every known harness, or the named ones (`claude-code`, `agents`; `codex` and `chatgpt` alias `agents`), or an explicit `--path`. `--project` installs into the current directory so the skill travels with a repository. `--list` shows every destination without writing. |

```console
$ arcavex skill install --list
target                           path                                              state
Claude Code                      C:\Users\you\.claude\skills\arcavex-design-studio  not installed
Codex / ChatGPT (Agent Skills    C:\Users\you\.agents\skills\arcavex-design-studio  not installed
standard)
```

A host reads its skills when it starts, so restart the assistant (or open a new session) after
installing. The same document is also served by the MCP server as the resource
`skill://arcavex-design-studio/SKILL.md`, for clients that connect over MCP rather than a shell.

## desktop

Commands Arcavex Desktop uses to check the engine it launches; not part of the authoring loop.

| Subcommand | Purpose |
|---|---|
| `handshake [--json]` | Report engine identity, compatibility versions, paths, capabilities, and health. |

## ext

Trusted local extension commands (spec §7). Full walkthrough in
[extension-guide.md](extension-guide.md).

| Subcommand | Purpose |
|---|---|
| `scaffold KIND DIR` | Scaffold a new, immediately-valid extension of the given kind. |
| `validate DIR` | Validate manifest, compatibility, imports, determinism, and schemas. |
| `test DIR` | Run the extension's golden fixtures in a crash-contained subprocess. |
| `add DIR` | Validate and add a local extension to the Arcavex home, recorded disabled. |
| `enable NAME` | Enable an added extension (its components register on the next run). |
| `disable NAME` | Disable an added extension (deregistered on the next run). |
| `list` | List every added extension, its enabled state, and its components. |

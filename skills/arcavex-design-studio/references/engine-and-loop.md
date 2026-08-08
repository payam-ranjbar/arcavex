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

## Context cost

`layout inspect --json` on a real poster is tens of thousands of characters. Do not page the whole
thing into context for every iteration — read the human output, or inspect one format at a time, and
reach for `--json` when you need to filter precisely.

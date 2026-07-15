# Phase 05 — DX & design review (MCP authoring surface)

Reviewer: Sonnet 5, DX/design lane. Scope: commit `eb50d77`. Read the brief
(`docs/agent-runs/phase-05-brief.md`) and spec §6.2, §6.3, §3.6, §3.7, §4.1.1, §4.1.4 before
starting. All work under `outputs-tmp/dx5/` with an isolated `ARCAVEX_HOME` at
`outputs-tmp/dx5/home`. Every claim below was produced by driving the real tool surface
in-process — the bound `ArcavexTools` methods *and*, for the load-bearing findings, the actual
built `FastMCP` server's `call_tool` dispatch (`server.call_tool(...)`) so nothing is a
reading-the-code inference. Repro scripts live at `outputs-tmp/dx5/loop*.py`.

## Verdict: **remediate**

The parts of this surface the implementer's own tests exercise are genuinely excellent —
diagnostics are located and hinted everywhere they fire, the debug overlay is a real working PNG
with node-id boxes I decoded and viewed, `layout_inspect` gives an agent honest numeric geometry
including overlap detection a compile-clean `validate` misses, and MCP/CLI JSON shapes are
provably byte-identical where both exist. But the moment I drove the loop past what
`tests/mcp_sessions/` covers — a template's own baked-in `preview_data`, never a project, never
an external data file — I hit a **P0 crash that breaks four of the eight core authoring tools
for the single most ordinary thing an agent does: pointing them at real data**, plus a
structural dead end where an agent can create a project and write data into it but has no
supported way to ever render that project or produce a run through MCP at all. The scripted
exit-criterion test passes because it never supplies external data or uses a project — it proves
a narrower claim than "an agent creates and corrects a poster."

## Findings

### DX-1 (P0) — the `data=` parameter is broken on `validate`/`render`/`render_preview`/`layout_inspect`; any external data file crashes with an opaque internal error

**Did:** scaffolded a project (`project_create`), wrote real data into it with `data_set`
(confirmed the write landed on disk correctly), then called `template_validate`/`render`/
`render_preview`/`layout_inspect` pointing at that data file — the ordinary next step after
authoring data. Reproduced through both the bound `ArcavexTools` methods and the real
`FastMCP` server's `call_tool` dispatch (`outputs-tmp/dx5/loop16_server_dispatch_databug.py`),
so this is exactly what a real MCP client sees, not an artifact of how I drove the callables.

**Happened:** every one of the four tools returns `ok: false` with a single, contentless
diagnostic:
```json
{"code": "ARC-INT-999", "severity": "error",
 "message": "Validation failed unexpectedly",
 "hint": "This is an internal engine error. Detail: AttributeError(\"'str' object has no attribute 'with_suffix'\")"}
```
I traced the two distinct crash sites (both string-vs-Path):
- `src/arcavex/services/template/loader.py:160` — `load_yaml(data)` calls `path.is_file()` on
  whatever `data` is; when `data` is a plain string this raises immediately, with **no locale
  involved at all** (reproduced with `locale=None`).
- `src/arcavex/services/template/compiler.py:968` — `_locale_data_overlays` calls
  `data.with_suffix("")` when a locale is also supplied.

Root cause: `src/arcavex/clients/mcp_server.py` passes `template`/`data` straight through to the
`Facade` as raw JSON strings (`data=data,  # type: ignore[arg-type]`) on `template_validate`,
`render`, `render_preview`, and `layout_inspect` — the `# type: ignore` comment is the tell; it
silences the exact mismatch that crashes. Every other path-like MCP argument in this same file
*is* converted (`Path(output)`, `Path(source)` for `asset_add`, `Path(target)` for
`project_create`/`project_clone`, `Path(run_dir)` for `run_rerun`) — `template`/`data` on these
four tools are the only ones left as bare strings. The CLI never hits this because Typer declares
`data: Path = typer.Option(...)` and coerces the string before the facade is ever called — same
facade method, different client, only one of them converts the type.

Isolation matrix (`outputs-tmp/dx5/loop14_isolate_bug.py`), all through the real tool wrapper:

| call | result |
|---|---|
| `render(data=<str>, locale="en")` | crash |
| `render(data=<str>, locale=None)` | crash |
| `render(data=None, locale="en")` | **ok** (only path that works — relies on `preview_data`) |
| `template_validate(data=<str>, locale="en")` | crash |
| `layout_inspect(data=<str>, locale="en")` | crash |
| `render_preview(data=<str>, locale="en")` | crash |

**Must change:** wrap `template`/`data` in `Path(...)` in `mcp_server.py` exactly as already done
for every other path argument in the same file (or make `loader.load_yaml`/
`compiler._locale_data_overlays` accept `str | Path` uniformly at the boundary). Then add a
session test that passes an **external data file** (not just relying on a template's
`preview_data`) through each of the four tools — the current `tests/mcp_sessions/` suite never
does this (every fixture and every call in `test_authoring_session.py` and
`test_create_and_correct.py` leaves `data` at its default `None`), which is exactly why this
shipped. This is the single highest-priority fix: it means an agent cannot author against real
content through any of the four inspection/render tools today, only against a template's
placeholder preview data.

### DX-2 (P0/P1) — no MCP tool can render a project or ever create a recorded run; `run_list`/`_diff`/`_rerun` have nothing to operate on

**Did:** continued the same project from DX-1: `project_create` → `data_set` → tried to render
it. `render`/`render_preview`/`layout_inspect`/`template_validate` all take `template`/`data` as
direct-file-mode arguments (`Path`), not a `project`; there is no `project` parameter anywhere on
these four tools. Passing the project directory as `template` fails outright
(`ARC-TPL-001 Directory template has no template.yaml`) because it isn't a template directory.
I then manually reconstructed the direct-mode call by reading `project_status()`'s `template`
(a path *relative to the project root*) and `data` fields, resolving them to absolute paths by
hand, and passing those — which is itself a real usability gap (an agent must reimplement path
resolution project.yaml already encodes) — and it still hits DX-1's crash, because `data` is
supplied explicitly.

**Happened:** the `Facade` has `render_project(project, formats, locales, dpi) -> RunReport` and
`record_render(template, data, ..., outputs_root) -> RunReport` — the two methods that actually
produce a recorded run (`manifest.json`, provenance) — and neither is wrapped by any MCP tool
(confirmed: `'render_project' in {m for _, m in _TOOL_METHODS}` is `False`, likewise
`record_render`). `arcavex_render` wraps only `render_file`, the unrecorded direct-mode path.
Meanwhile `arcavex_run_list`, `arcavex_run_diff`, and `arcavex_run_rerun` **are** in the MCP tool
set — three tools promising run management with no MCP-reachable action that ever originates a
run for them to act on. Confirmed empirically: after the manual-reconstruction render attempt
(which failed on DX-1 anyway), `run_list(project=...)` reports `runs: []`.

**Must change:** add `arcavex_project_render` (wrapping `render_project`) so an agent that just
created a project and authored data through `project_create`/`data_set`/`data_import` has a
supported way to render it and get a recorded run — completing the lifecycle the three
run-management tools already assume exists. Consider also wrapping `record_render` for
direct-mode provenance, matching the CLI's `render --record`.

### DX-3 (P1) — `template_inspect` never reports locales, though spec §4.1.1 promises it does

**Did:** ran `template_inspect` on `examples/ipen-bilingual` (a template that declares
`locales: {en: {direction: ltr}, fa: {direction: rtl, digits: fa, fonts: ..., patch: ...}}`,
verified by reading the template source only *after* confirming the gap). Compared the MCP tool
output against `arcavex template inspect --json` on the same template — the two are byte-for-byte
identical (`outputs-tmp/dx5/loop6_parity.py`), so this isn't an MCP-vs-CLI divergence, it's a gap
in the underlying `TemplateInspectReport` model both clients share.

**Happened:** `TemplateInspectReport`'s fields are `variables`, `formats`, `nodes`, `functions`,
`preview_data` — no `locales` field exists at all. Spec §4.1.1 states explicitly: "`arcavex
template inspect --json` returns variable types, formats, **locales**, node IDs, registered
components, and example data so an AI does not need to infer the contract from raw source." An
agent inspecting this template today has no way to learn it supports `en`/`fa` except by
guessing a locale and reading the resulting error. That error, when I tried `locale="xx"`, is
genuinely excellent (`ARC-TPL-100`, hint: `"Declare it under 'locales:', or use one of: en, fa."`)
— but it's a reactive discovery path (deliberately fail, read the hint), not the proactive
contract inspect is supposed to be.

**Must change:** add a `locales: list[LocaleInfo]` field to `TemplateInspectReport` (name,
direction, digits at minimum) so this is discoverable without triggering an error first.

### DX-4 (P1) — `template_patch` accepts any field name under a valid node id with zero schema check; a typo silently corrupts the file until the next `validate`

**Did:** patched `nodes.title.style.fontsize` (typo for `font_size`) on a working copy of
`ipen-bilingual`.

**Happened:**
```json
{"ok": true, "applied": 1, "sha256": "...", "diagnostics": []}
```
The patch tool reports success. It wrote `fontsize: 80pt` as a **new, bogus key** into the YAML
sitting right next to the pre-existing correct `font_size: 80pt` (confirmed by reading the file).
`template_patch` validates that the addressed *node id* exists (confirmed separately: patching
`nodes.doesnotexist.style.fill` correctly errors with `ARC-TPL-092` and a good hint) but performs
no check on the *leaf field path* at all. The very next `template_validate` call does catch it,
with an excellent located diagnostic:
```
ARC-TPL-051  Node 'title' has unknown style field 'fontsize'
hint: Valid style fields are: align, color, corner_radius, direction, fill, font, font_size,
      font_weight, italic, letter_spacing, opacity, stroke, stroke_width.
```
So it's recoverable — but only if the agent remembers to validate before trusting the patch's own
`ok: true`. The spec's AI workflow (§6.3) lists "apply patches" and "validate" as separate,
sequential steps for exactly this reason, but `patch_template`'s success response gives no signal
that a field-level problem might still be waiting, and an agent that (reasonably) treats
`applied: 1` as "the edit took" and moves straight to `render_preview` will render successfully
(unknown style keys are just ignored at render time) without ever learning its edit was silently
a no-op-plus-garbage.

**Must change:** have `patch_template` run the same field-schema check `validate` already has
against the addressed node's type before writing, and return the `ARC-TPL-051`-class diagnostic
in the patch response itself instead of only surfacing it on a separate call.

### DX-5 (P2) — no MCP tool for style/effect catalogs, though the facade methods (with full parameter schemas) already exist and are already wrapped for the CLI

**Did:** searched for a way to discover valid style names or effect names/parameters before
guessing. `arcavex mcp tools --json` lists 19 tools; none of them list styles or effects.
Checked the facade directly: `Facade.list_styles`, `Facade.inspect_style`, and `Facade.list_effects`
all exist, are used by `arcavex style list/inspect` and `arcavex effects list/inspect`, and
`list_effects()` returns genuinely rich structured data an agent would want (per effect: name,
category, and a full parameter list with type/required/default/constraint — e.g. `blur`'s
`radius: {type: length, required: false, default: 4.0, constraint: ">=0"}`).

**Happened:** patching in a bogus effect name (`made-up-glow`) and a bogus style ref
(`does-not-exist@9.9`) both produced excellent recovery hints on the next `validate`
(`"Registered effects: blur, channel-offset, drop-shadow, ..."` /
`"Available styles: pop-art."`) — so an agent that guesses wrong once *can* recover the full
vocabulary from the error. But it never gets parameter schemas this way (only names), and it's a
guess-then-read-the-error loop rather than a real discovery call, for two categories (styles,
effects) that are core to template authoring and for which the exact same thin-wrapper pattern
used for the other 19 tools would cost almost nothing to add — the versioned response models
(`StyleListReport`, `EffectListReport`) already exist.

**Must change:** add `arcavex_style_list`, `arcavex_style_inspect`, and `arcavex_effects_list`
mirroring the CLI, closing the one real "how would an agent know that" gap left in the catalog.

### DX-6 (P2) — `data_set`/`data_import` don't validate the keypath against declared variables; a typo is a silent, undetectable no-op

**Did:** called `data_set("titel", "New Title", project=...)` (typo for `title`) against a
project whose template requires `title`, seeded from `preview_data` so the variable already had a
value.

**Happened:** `{"ok": true, "diagnostics": []}`. The tool wrote a new, dead `titel:` key into the
project's data file; the real `title` the agent meant to change was untouched. Because `title`
already had a value (from the `preview_data` seed at `project_create` time), the "revalidate"
step the docstring promises finds nothing missing and reports clean. From the agent's point of
view the edit "worked" (`ok: true`) and produces no signal that it did nothing — this is worse
than DX-4's typo case because there's no later `validate` step that would ever catch it (an
unused data key isn't an error the way an unknown style field is).

**Must change:** have `data_set`/`import_data` warn (not necessarily error, since intentionally
extra data may be legitimate) when a top-level keypath segment doesn't correspond to any declared
template variable, so an agent gets *some* structured signal instead of silent success.

### DX-7 (P3) — tool catalog is otherwise clean and self-documenting, but says nothing about the two broken paths above

**Did:** read `arcavex mcp tools --json`'s full catalog cold, as an agent seeing this server for
the first time would.

**Happened:** genuinely good — 19 tools, each name and first-line description maps cleanly
1:1 onto a CLI command and a `Facade` method (verified: `test_every_tool_delegates_to_a_facade_method`
holds, and I independently confirmed `_TOOL_OUTPUT_MODELS` schemas are exactly the `Facade`
model's `model_json_schema()`, byte for byte, for every structured tool). The server's
`instructions` field spells out the intended inspect→patch→validate→preview→layout_inspect→render
loop in one paragraph, which is exactly the right amount of steering. No confusing overlaps.
The one gap: nothing in any tool's description hints that `data=` is currently non-functional
(DX-1) or that `render`/`render_preview`/etc. only cover direct-file mode, not projects (DX-2) —
an agent has no way to know these paths are landmines until it hits them.

## §11 Phase-5 exit-criterion audit

> "An agent creates and corrects a poster using ONLY supported template operations... every MCP
> capability also reachable via CLI/API."

**Partially met — narrower than it looks.** I reproduced the implementer's own scripted scenario
by hand (seeded broken template on disk → `template_validate` finds `ARC-IR-030` →
`diagnostic_explain` → `template_inspect` for the node id → `template_patch` the fill color →
re-`template_validate` green → `render` a real PNG) end to end through the *real* `FastMCP`
`server.call_tool` dispatch, including decoding the base64 image content myself
(`ImageContent`, `mimeType: image/png`, 327KB payload) — this genuinely works, is not a stub, and
is a fair demonstration of "correct from structured diagnostics using only supported operations."

But that scenario only exercises a template's own baked-in `preview_data`, never a project, never
external data — and the moment I extended the same loop to the realistic version this phase's own
scope was built for (`project_create` → `data_set`/`data_import` → render the project), it broke
at two separate points: DX-1's crash on any real data file, and DX-2's total absence of a
project-mode render path. Given `data_set`, `import_data`, `add_asset`, and `annotate_asset` are
all named as required v1 deliverables in the brief specifically because an agent is expected to
author *real* content (not just patch a template's placeholder), I don't think the exit criterion
is met for the workflow the phase was actually scoped to deliver — only for the narrower
template-only correction loop the test suite happens to cover.

"Every MCP capability also reachable via CLI/API" — inverted check also holds real gaps:
`arcavex template inspect --resolved` (facade's `inspect_resolved`, spec §4.1.4's per-layer
provenance view) and `style`/`effects list/inspect` are CLI-only with no MCP tool, though the
brief doesn't claim these are required and the v1 MCP tool list in spec §6.2 doesn't name them —
so this is scope-consistent, not a violation, but still real friction (DX-5).

## Agent authoring loop — walkthrough with friction log

1. **Discover** (`template_inspect` on `examples/ipen-bilingual`) — variables (with
   required/default/doc), formats (both authored strings *and* resolved pt, so no unit
   conversion needed), node ids/types, and every registered template function with a real
   signature and doc line, all in one call, no source read. Genuinely good. *Friction:* no
   locales (DX-3); `NodeInfo` gives id/type only, never current field values or a per-type field
   list — an agent must learn valid style/constraint keys either from prior knowledge or from
   triggering a validate error, never from inspect itself (this is consistent with spec's
   literal promise — "node IDs," not full node dumps — but it's the reason DX-4's typo is
   possible to make in the first place).
2. **Patch** (`template_patch`, path-addressed, `nodes.<id>.<field...>`) — comment-preserving
   round-trip confirmed (a scaffold's authoring comment survived a patch in the implementer's own
   test, which I re-verified). Node-id existence is checked with an excellent diagnostic;
   `insert_after`/`insert_before`/`remove` all work. *Friction:* leaf field paths are never
   checked (DX-4); `base_sha256` concurrent-edit protection works exactly as documented
   (`ARC-TPL-110`, clear hint) — the one place a "the file changed under me" scenario is handled
   well.
3. **Validate** — the best-behaved tool in the surface. Every diagnostic I triggered (invalid
   color, under-constrained layout axis, unknown style field, unknown effect, unknown style ref,
   unknown locale) was located (file/line/keypath), coded, and hinted with either the exact fix
   or the full valid vocabulary. This is where the "no catalog tool" gaps (DX-5) get partially
   bailed out — reactively, not proactively.
4. **Preview + debug overlay** — real base64 PNG confirmed through actual server dispatch; the
   `debug=true` overlay is a genuinely useful artifact, not a description of one — I decoded and
   viewed it and it shows every node's id label and bounding box correctly positioned over the
   real render.
5. **layout_inspect** — numeric `bounds_pt`/`bounds_px`, per-axis anchor derivation chains
   (`"accent-bar.bottom + 18pt" → 401.4pt`), and `overlaps` all confirmed accurate against a
   layout problem I constructed by hand (an under-constrained node, then a genuine sibling
   overlap once fixed) — and confirmed that `validate` alone does *not* catch the overlap
   (compile-clean, geometrically wrong), so an agent must run both steps, matching the spec's
   intended two-step design rather than being a gap.
6. **Render (data-less)** — works, produces a real PNG with a content hash.
7. **The realistic version — a project with real data** — this is where the loop breaks. Steps
   1–4 above all silently assumed the template's own placeholder `preview_data`. The instant I
   substituted a project's real authored data (the entire point of `data_set`/`import_data`),
   every one of validate/render/preview/layout_inspect crashed (DX-1), and there was no
   project-mode render tool to fall back to (DX-2).

## What impressed

- **The debug overlay is real, not a stub.** I decoded the base64 PNG from an actual
  `server.call_tool` response and viewed it — correct node-id labels and bounding boxes over a
  correctly-rendered poster, including the diamond-grid mask and the patched title font size.
- **Diagnostics are uniformly excellent wherever they fire** — six different failure classes I
  triggered by hand (bad color, unknown style field, unknown effect, unknown style ref, unknown
  locale, under-constrained layout axis) every one located, coded, and hinted with either the
  precise fix or the complete valid vocabulary. This is the part of the spec's §3.6 claim
  ("simultaneously the human authoring experience and the AI self-correction loop") that is
  fully delivered.
- **`layout_inspect` catching a real overlap that `validate` misses** — I built the failing case
  myself (two siblings both anchored to `parent.top`/`parent.left` with identical size) and the
  tool reported it exactly as spec promises (`overlaps: [SiblingOverlap(a='box', b='title', ...)]`,
  `covered_fraction: 0.0706`), correctly distinguishing "compiles" from "looks right."
- **Schema parity is real, not just tested-and-hoped.** I independently diffed
  `template_inspect`'s MCP output against `arcavex template inspect --json` on the same template
  and they are byte-for-byte identical; the patch tool's input schema genuinely reuses the shared
  `PatchOp` model (`$defs.PatchOp` matches field-for-field).
- **`base_sha256` concurrent-edit detection** works exactly as documented — a stale hash produces
  a located, actionable `ARC-TPL-110` rather than silently overwriting a concurrent edit.

## Repro artifacts

All under `outputs-tmp/dx5/` (scratch, not for commit): `loop1_discover.py` through
`loop16_server_dispatch_databug.py`, plus their captured output files. `loop14_isolate_bug.py`
is the isolation matrix for DX-1; `loop12_project_render_gap.py`/`loop13_traceback.py` for DX-2;
`loop6_parity.py` for the MCP/CLI byte-identity check; `debug_preview.png` is the decoded debug
overlay I viewed.

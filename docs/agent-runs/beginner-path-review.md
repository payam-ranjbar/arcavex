# Beginner path — UX review (a non-technical person and their AI assistant)

Reviewer: Claude Fable 5.1 orchestrating seven contextless tracer agents, one independent verifier
per finding, and a merge agent, on 2026-09-04. Branch under review: `codex/desktop-phase2` at
`d0cbc0d` (a fresh clone, so the tracers met exactly what a download meets). Fixes land on
`codex/beginner-ux`. Sandboxes lived under `C:\Users\payam\Downloads\arcavex-beginner\`; every
agent ran with an isolated `ARCAVEX_HOME`, `UV_TOOL_DIR` and skill `--path`, so nothing here touched
the developer's real configuration. Workflow: 63 agents, 53 minutes, 3.7M tokens; MCP transcripts
recorded per call.

## The question

A person who cannot help with technical steps downloads Arcavex and asks an AI assistant — in
Claude Code, Codex CLI, or Claude Desktop — to "set it up and make me a poster". They describe the
design in whatever detail they like. Where does that path break, where does it merely drag, and what
does the assistant have to guess?

The brief every live trial received, verbatim:

> "I downloaded this arcavex thing from GitHub. I run a small neighbourhood bakery called Golden
> Crust. We're opening a second shop on Saturday 26 September at 9 am, at 14 Elm Street. I want a
> poster for the shop window and a square version for Instagram. Warm, friendly, a bit retro. I
> don't have a logo. Can you make it?"

## Method

Seven tracers, each blind to the others, each returning findings with verbatim evidence:

| Tracer | Angle | Kind |
|---|---|---|
| T1 docs | Read README → install → quick start → CLI reference → skill as the assistant would, checking every cheap factual claim (PyPI, releases, example paths, host-connection commands) | static |
| T2 install | Follow the docs literally from a fresh clone to a healthy `arcavex doctor`, skill install, MCP catalog, first render; then the global-command route (`uv tool install`) | live |
| T3 hosts | Register the server with Claude Code, evaluate the Claude Desktop and Codex paths, and meet the server as a fresh MCP client | live |
| T4 shell brief | Be Claude Code for the bakery owner: install from the clone's own docs, learn the skill, design both posters, look, iterate, hand off | live, 17 min |
| T5 MCP-only brief | Be Claude Desktop: only the MCP tools, through a recording proxy that saves the returned preview images; no docs, no files | live, 131 tool calls |
| T6 see-result | How the person sees and reacts to a render; how the assistant looks at pixels; the `--watch` and desktop stories | mixed |
| T7 skill drift | Every command, flag, tool name, resource, code and path the skill mentions, checked against the engine | static |

Every finding then went to an independent verifier told to *refute* it, reproduce it if reproducible,
and rate it for this reader: **P0** the path is blocked or the person gets a wrong result without
knowing; **P1** a wrong turn, a misleading claim, or a retry loop; **P2** friction or polish. The
verifiers refuted nine tracer claims (listed at the end) and sharpened several others; the merge
agent deduplicated the rest into the list below.

## Verdict: **remediate, then re-run**

Once the engine is installed and connected, the path works: the shell-based assistant went from a
fresh clone to two finished posters in seventeen minutes, with three deliberate revisions and a
byte-identical determinism check, and the MCP-only assistant delivered a good square from nothing
but the tool catalog and the served skill. Everything before that point was broken or undocumented
for this reader — the first command in the README, the install command, the connection to the host,
the MCP server itself on a runtime install — and everything after it (seeing the result, iterating
live, changing one format only) was left to the assistant to invent. The MCP-only assistant's
window poster is a 9:16 compromise because nothing over MCP can declare a print format.

### Where the path stands, stage by stage

| Stage | Verdict | What the tracers met |
|---|---|---|
| discover | **friction** | README opens with engine internals, two commands that fail as written (hello-poster, `uv pip install arcavex`), and an 'Arcavex Desktop' section with no download and no note that it is unreleased; the first beginner pointer ('New here?') is at README.md:72, and the one path that works from scratch (`template new`) is two clicks deep behind a failing quick start. |
| install | **friction** | Both README install routes are dead (arcavex is not on PyPI, zero GitHub releases; the one-liner also omits `uv venv`). docs/install.md's from-source route (`uv venv` + `uv pip install -e ".[dev]"`) works in ~5 s with doctor all-ok, but nothing tells a Windows beginner how to get uv/Python, and `arcavex` is not on PATH afterwards. |
| connect-host | **blocked** | On any runtime install (`uv tool install`, `uv pip install`, `pip install -e .`) `arcavex mcp serve`/`mcp tools` crash with ModuleNotFoundError: No module named 'mcp' (dev-only extra) and doctor does not flag it; no document gives a `claude mcp add` / claude_desktop_config / codex config recipe, and the skill tells the assistant to 'tell the user how to connect the engine' with nothing to cite. Only a dev-extra install plus the assistant's own MCP knowledge got a server registered (and then only 'Pending approval'). |
| learn | **friction** | Quick-start steps 1-3 and 5 reference poster.yaml/event.yaml that never shipped, step 4/5 use a nonexistent `a4` format and fabricated output, and the README claims 24/25 MCP tools against 46 live. The skill is 33/36 accurate but names `project render` (nonexistent) and omits the start-from-nothing MCP tools; style keys and generator params are documented only in Python source. The tutorial's `template new` path works end-to-end. |
| design | **friction** | Over the CLI a competent assistant authored a two-format bakery poster (square + A3 print with bleed) in three iterations with excellent located diagnostics (ARC-LAY-057). Over MCP alone, formats/variables/preview_data are unreachable and format/locale are not expression variables, so a print-size poster and per-ratio recomposition are impossible; scaffold placeholder copy leaks into project data; the inset-frame idiom and generator params are undiscoverable. |
| see-result | **friction** | render/preview/--watch are fast (engine work <0.5 s, ~1.1 s process startup), deterministic (identical SHA-256 across runs) and correct; `arcavex_render_preview` returns the image to the assistant. But the README's shipped example fails on a fresh home (ARC-FX-910, ext add/enable undocumented), no doc or skill step says how the person gets to see the file, `render` reports a CWD-relative path, and the preview path wraps mid-filename at 80 columns. |
| iterate | **friction** | The CLI loop (validate → render → look → layout inspect → revise) worked three times over; `preview --watch` re-renders 0.5-1.5 s after a save. Over MCP, `arcavex_editor_apply` with target.format returns ok:true but writes the shared node (P0 silent cross-format change); layout inspect buries real collisions under 10-12 intentional 'content' overlaps; the preview slot is shared across data/DPI variants; --watch is absent from quick-start, skill, and MCP. |
| deliver | **friction** | Both tracers delivered posters (t4: Instagram PNG + print-ready A3 PDF with correct MediaBox/TrimBox, opened for the person with Invoke-Item on its own initiative; t5: square tile good, 'window' poster a 9:16 compromise). No document tells the assistant to hand over the absolute path or open the file; no board/contact-sheet command exists though the skill says 'show the strongest board'; project_render applies one dpi to every format. |

## Findings (5 P0 · 14 P1 · 27 P2)

Ranked by severity, then by how early on the path the issue bites. *Status* is as of this document's
last regeneration; commits are on `codex/beginner-ux`.

### BX-01 (P0, install, docs) — Every documented distribution channel is dead: `uv pip install arcavex` / `pip install arcavex` (README and skill) target a package not on PyPI, and the README's fallback GitHub release page has zero releases

**Evidence.** README.md:22 `uv pip install arcavex     # or: uv pip install -e ".[dev]" from a clone`; README.md:26-27 "Releases also attach the wheel to the GitHub release page"; skills/arcavex-design-studio/references/engine-and-loop.md:16 "If nothing works, the user installs with `pip install arcavex` (or `uv pip install arcavex`), then `arcavex skill install`" (identical in the bundled skill the engine installs). Observed (multiple verifiers, fresh venvs): uv -> "Because arcavex was not found in the package registry and you require arcavex, we can conclude that your requirements are unsatisfiable" exit 1; `pip index versions arcavex` -> "No matching distribution found"; `curl https://pypi.org/pypi/arcavex/json` and `/simple/arcavex/` -> HTTP 404; `gh release list -R payam-ranjbar/arcavex` -> empty (repo public, auth ok); releases and tags REST endpoints -> 0; `git ls-remote --tags` -> empty. The release workflow (.github/workflows/release-engine.yml:223-226, `uv publish` + softprops/action-gh-release) exists but has never fired. pyproject.toml declares arcavex 0.1.0. The only working route is the parenthetical clone path `uv venv` + `uv pip install -e ".[dev]"` (docs/install.md:17-18).

**Impact.** The beginner's assistant is blocked at its first command. The skill, when it cannot find the engine, sends the user to the same nonexistent package, creating a retry loop between README and skill; the release-page fallback is also empty, so both README install routes are exhausted before install.md is read.

**Fix.** Make the clone route (`git clone` -> `uv venv` -> `uv pip install -e .`) the primary instruction in README and skill until arcavex 0.1.0 is published to PyPI / a release wheel exists. (`README.md:19-27 (install section) and skills/arcavex-design-studio/references/engine-and-loop.md:16 (mirrored into the bundled skill at build time)`)

**Status: fixed.** `f640a53`, `d76dd5b` — README and install docs lead with `uv tool install --python 3.12 git+https://github.com/payam-ranjbar/arcavex`, say PyPI is not published yet, and give the Windows-without-Python route; `67079d1` — the skill says the same. Cutting a release stays the maintainer's decision

<sub>Sources: t1:T2-01, t1:T2-02, t7:T7-01, t4:T4-01 (verifier observed registry failure), t2:T2-05 (verifier observed registry failure)</sub>

### BX-02 (P0, connect-host, bug) — MCP server is unusable from any runtime install: `mcp` is a dev-only dependency, so `arcavex mcp serve`/`mcp tools` crash with a raw traceback and `doctor` reports all-ok

**Evidence.** pyproject.toml:29-39 `dependencies` has no mcp; :41-48 `[project.optional-dependencies] dev = [... "mcp>=1.28,<2" ...]`. src/arcavex/clients/mcp_server.py:27 `from mcp.server.fastmcp import FastMCP, Image`; cli.py:1737/1751 import it without catching ImportError. Reproduced by two verifiers on `uv tool install <clone>` and on `uv venv` + `uv pip install -e <clone>`: `arcavex mcp tools`, `mcp tools --json`, `echo | arcavex mcp serve` -> rich traceback ending "ModuleNotFoundError: No module named 'mcp'" exit 1; `arcavex doctor` on the same install -> every row ok, no mention of mcp. README.md:22 leads with a runtime install; docs/install.md:30 explicitly says "For a runtime-only install, drop it: `pip install -e .`"; README.md:310/321 present the MCP server as shipped ("Wire it into an MCP client ... running `arcavex mcp serve`"). Repair attempts: `uv tool install --force --with mcp` pulls mcp 2.1.1 -> "No module named 'mcp.server.fastmcp' ... FastMCP was renamed to MCPServer" still exit 1; only `--with "mcp>=1.28,<2"` (mcp 1.29.1) yields 46 tools. No `[mcp]` extra exists and no doc names one. Verifier severities: t2 P0, t4 P1 (CLI path still works; fix inferable from traceback + install.md:30).

**Impact.** Anyone who installs the way the README leads with (or `uv tool install`, or the runtime-only `pip install -e .`) gets a CLI whose MCP server crashes, so the assistant cannot connect the engine to Claude Desktop/Claude Code/Codex; for a no-shell host this is the only engine path and it is blocked. The obvious repair also fails (mcp 2.x). Only clone installs that keep the `.[dev]` extra work.

**Fix.** Move `mcp>=1.28,<2` into runtime `dependencies` (or add an `[mcp]` extra documented everywhere MCP is advertised) and replace the bare import traceback with a coded diagnostic naming the install command. (`pyproject.toml:29-49 (`dependencies` / `[project.optional-dependencies]`), with src/arcavex/clients/cli.py:1737,1751 as the secondary site for a coded ImportError hint`)

**Status: fixed.** `c3fabea` — `mcp` is a runtime dependency; packaging tests pin it

<sub>Sources: t2:T2-03, t4:T4-03</sub>

### BX-03 (P0, design, ai-ux) — Over MCP alone there is no way to declare a format/canvas, variable, preview_data or per-format patch, and `template_new` silently ignores format arguments — a print-size poster and per-ratio composition are impossible for a chat-only assistant

**Evidence.** Reproduced by verifier over the recording proxy: `arcavex_template_new {target, format:"poster"}` and `{formats:[{id:"a3",...}]}` -> ok:true, "format":"square", scaffold holds only square 1080x1080 and story 1080x1920 (MCP signature is `template_new(target, name)`, mcp_server.py:129; CLI has no format option either). `arcavex_template_patch` with `{set:"formats.a3"}`, `variables.city`, `preview_data.title`, `formats.square.patches` -> all ARC-TPL-092 "patch path ... must be 'nodes.<id>[.<field>...]'" (hard-coded at services/template/overlays.py:161-165). Node text `{{ format }}` -> ARC-TPL-014 "references undefined variable 'format'". `render_preview format=a3` -> "Unknown format 'a3' ... Available formats: square, story". `arcavex_editor_apply` command kinds (mcp_server.py:252-262) are all layer-level; `project_create.formats` only selects among formats the template already declares. The skill itself demands per-format composition: SKILL.md:122 "Do not scale or crop one master canvas"; references/multi-format.md:24-25 "encode it (`if:` / format patches)". Tracer's window poster therefore shipped as a 9:16 'story' canvas with one shared node tree.

**Impact.** A chat assistant restricted to MCP can produce only the stock square and story canvases; the skill's own multi-format guidance cannot be followed; a person cannot get an A3/A4 poster through a chat-only host; and `template_new` returns success for a format request it did not honour, so the assistant believes it asked for a poster format. Blockage is specific to MCP-only hosts (a shell-capable assistant can write template.yaml directly).

**Fix.** Expose a template-level authoring surface over MCP (formats/canvas, variables, preview_data, formats.<f>.patches — via template_new options or a template-level patch) and reject unknown template_new arguments instead of ignoring them. (`src/arcavex/clients/mcp_server.py (template_new at :129, template_patch at :161) and services/template/overlays.py:161-165`)

**Status: fixed.** `96b49d9` — `template patch` (CLI and MCP) can set or remove `formats.<name>`, `variables.<name>`, `preview_data.<key>`, `locales.<name>` and `style`, and every patch is compiled for each declared format and rolled back if it introduces an error; `e988859` — nine canvas presets for `template new`. Proved live over MCP: two ops declared A3 and rendered 3508×4961

<sub>Sources: t5:T5-02</sub>

### BX-04 (P0, see-result, docs) — The README's and quick-start's shipped-example render (future-archive-poster) fails ARC-FX-910 on a fresh install because the bundled `archive-print` extension is not enabled, and no beginner-path doc or the error hint gives the `ext add`/`ext enable` commands

**Evidence.** README.md:120 `arcavex render examples/future-archive-poster/template.yaml --format square -o out.png`; docs/quick-start.md:78-79 and :107-108 same template. Observed on fresh ARCAVEX_HOME (three verifiers, CLI and MCP `arcavex_template_validate`): "ERROR ARC-FX-910 Node 'main-photo' references unknown effect 'archive-print' ... hint: Registered effects: blur, channel-offset, ... torn-paper." exit 1 — the hint lists registered effects but never mentions `ext add`/`ext list` or the sibling extensions/ directory. grep `ext (add|enable)` over README.md, docs/quick-start.md, docs/install.md, examples/future-archive-poster/README.md -> only README.md:51 (generic `./my-effect` / `grain-warp`); examples/future-archive-poster/README.md:45 says "after adding and enabling the extension:" with no command. The commands do exist two levels down (examples/future-archive-poster/extensions/archive-print/README.md:12-13 as `arcavex ext add .`; examples/graphic-style-lab/README.md:27-28 full-path form). Fix verified: `ext add examples/future-archive-poster/extensions/archive-print` -> "Added archive-print (enable it next)"; `ext enable archive-print` -> "Enabled"; rerun -> Rendered, 2,293,131-byte 1080x1080 PNG. Combined with BX-12 the README currently has no working copy-paste render. Verifier severities: t1 P0 (blocked at the first real poster), t2 P1 (loud error, recoverable in one guess).

**Impact.** The only shipped poster example the README and quick start point at errors out on first try; the assistant must infer the two commands from an unrelated custom-effect snippet or dig into nested READMEs. Together with BX-12, a beginner has zero documented render that works from a fresh clone.

**Fix.** Add `arcavex ext add examples/future-archive-poster/extensions/archive-print && arcavex ext enable archive-print` immediately before every future-archive render on the beginner path, and make the ARC-FX-910 hint point to `ext add`/`ext enable` when a sibling extensions/<name> matches. (`README.md:120 (Examples code block) and docs/quick-start.md before its first future-archive render; examples/future-archive-poster/README.md:45; ARC-FX-910 hint in the compiler`)

**Status: fixed.** `7249c6d` — README and quick start carry the two `ext` lines; `b1b6ea7` — the ARC-FX-910 hint says how an extension gets an effect registered

<sub>Sources: t1:T2-05, t2:T2-02</sub>

### BX-05 (P0, iterate, bug) — `arcavex_editor_apply` accepts `target.format` but writes the change into the shared node for every format, returning ok:true with no diagnostic (silent cross-format edit)

**Evidence.** Reproduced by verifier from scratch (template_new -> project_create square+story -> template_detach -> project_snapshot -> editor_apply {target:{format:"story"}, commands:[{kind:"resize", layer_id:"accent", w_pt:750, h_pt:1380}]}): response "ok": true, "changed": [{"path": "templates/tpl/template.yaml"}], "changed_layer_ids": ["accent"], inverse.target = {"format":"story"}, "diagnostics": []. Template diff: shared node `size: {w: 180px, h: 12px}` -> `{w: 750pt, h: 1380pt}`; no formats.story.patch written; overrides/ empty. `layer_tree` for format "square" then reports the node at bounds_pt [48,300,750,1380] on an 810pt canvas — off-canvas in the non-targeted format with no warning. Tracer's own call (t5 transcript line 196) identical. By design: kernel/editor.py:69-72 "Structural edits apply to the authored document regardless of target, but validation ... need to know which target the user was looking at"; services/editor/service.py:262-271 uses target only for `_validate_staged(...)`. Neither the tool description (mcp_server.py:246) nor the skill (engine-and-loop.md:82) says target does not scope the write, while the template language offers `formats.<name>.patch` (docs/template-schema.md:63).

**Impact.** The assistant asks for a story-only resize, gets a clean success, and the square Instagram tile is silently changed too; the wrong tile is noticed only if the other format is re-rendered afterwards. A non-technical person would receive a wrong deliverable without anyone being told.

**Fix.** Either write format-scoped commands into formats.<name>.patch (and report it in `changed`) or refuse a format-targeted structural command with a coded diagnostic — never return ok with an ignored target. (`src/arcavex/services/editor/service.py (apply path ~line 262 where transaction.target is consumed only for validation); mirror contract in src/arcavex/clients/mcp_server.py:246 and skills/.../engine-and-loop.md:82`)

**Status: in progress.** editor agent: `target` documented as the validation/preview context everywhere; new `scope: format` writes `formats.<f>.patch`; structural commands under it are refused with a code

<sub>Sources: t5:T5-01</sub>

### BX-06 (P1, discover, docs) — README advertises a Windows desktop application with no download link, no statement that it is unreleased, and no CLI/MCP way to open a project in it

**Evidence.** README.md:75-88 "## Arcavex Desktop / The Windows desktop application is the same engine with a window on it..." — only link is docs/desktop/editor.md; README.md:108 lists 'Desktop editing'. The only release link in README is :26-27 for the wheel (and there are zero releases). grep download|installer|.exe|.msi over README, docs/install.md, docs/quick-start.md, docs/desktop -> nothing beyond .venv/Scripts/arcavex.exe and editor.md:118 'the engine the installer shipped'. Build path exists only in packaging/README.md:130 (`cd apps/desktop; npm ci; npm run tauri build # -> ...\bundle\nsis\*-setup.exe`), a developer doc; apps/desktop has no README. apps/desktop/CHANGELOG.md:11-12 "## Unreleased / The Foundation and Phase 1 viewer, not yet published as a `desktop-v*` release" — a fact the README does not carry. `arcavex desktop --help` -> only `handshake`; `arcavex desktop open .` -> "No such command 'open'" rc=2; no top-level command or MCP tool launches a window; the desktop exe's only CLI is headless `--self-check`; docs/cli.md:25 'There is no persistent "open project" state.'

**Impact.** A non-technical Windows user reads 'Windows desktop application' and expects an installer; the assistant hunts the empty releases page and docs, wasting the first minutes on a wrong turn, and when asked 'can I see it in the app?' has nothing to run.

**Fix.** State in the README that the desktop app is not yet released (link where the installer will appear, mirroring apps/desktop/CHANGELOG.md:11) and route readers to the CLI/MCP path; later add `arcavex desktop open [PROJECT]`. (`README.md:75-88 ("## Arcavex Desktop" section)`)

**Status: fixed.** `f640a53` — the README says plainly that no installer exists yet and routes the reader to the CLI/MCP path; `arcavex desktop open` deferred

<sub>Sources: t6:T6-05, t1:T2-13 (unverified)</sub>

### BX-07 (P1, install, docs) — README's install one-liner omits `uv venv` (fails 'No virtual environment found'), no doc tells a Windows beginner how to get uv/Python, the uv path never mentions activation so `arcavex` is not on PATH, and the global `uv tool install` route is undocumented

**Evidence.** README.md:21-24 shows `uv pip install arcavex` then `arcavex doctor` with no venv/activation step. Observed (three verifiers, uv 0.11.2): `uv pip install arcavex` and `uv pip install -e ".[dev]"` in a dir with no venv -> "error: No virtual environment found; run `uv venv` to create an environment, or pass `--system`" exit 2. docs/install.md:5 "Python 3.11+ is required", :11 "create a virtual environment. The project targets uv" — the only pointer to obtaining uv; nothing on obtaining Python; grep winget|install uv|astral|python.org|prerequisite over all .md -> nothing beyond the astral link. install.md:17-18 `uv venv` / `uv pip install -e ".[dev]"` has no activation line (the pip path at :25 does). After `uv venv`+install, bare `arcavex --version` -> "command not found" exit 127; binary location is disclosed only at install.md:32-33 / quick-start.md:5-6 (`.venv/Scripts/arcavex.exe`). `uv venv` with no --python picked system Python 3.14.0 on one machine (doc reference is 3.12). grep 'uv tool'|pipx|update-shell over README, install.md, quick-start.md, packaged-install.md, cli.md, contributing.md -> zero hits; `uv tool install <clone>` works for the CLI (doctor ok, 92M) but warns "`...uv-bin` is not on your PATH ... or `uv tool update-shell`", still lacks mcp (BX-02). No doc says to restart the host or use the full exe path in host configs (see BX-08).

**Impact.** Followed literally, README.md:22 fails; the assistant must invent uv/Python installation, the venv step, and activation or full-path usage; every bare `arcavex ...` line in the README fails until it does. Recoverable via uv's own hint and install.md, so a wrong turn rather than a block.

**Fix.** Add a Windows prerequisites block (install uv, `uv venv --python 3.12`, activate or use `.venv\Scripts\arcavex.exe`, optional `uv tool install` + `uv tool update-shell`) and make README.md:22 read `uv venv && uv pip install -e .` from the clone. (`docs/install.md:5-19 (Windows prerequisites block) and README.md:19-24 (install snippet)`)

**Status: fixed.** `f640a53`, `d76dd5b` — global-command route first, `winget install astral-sh.uv` for a machine without Python, the PATH warning and `uv tool update-shell`, the venv alternative spelled out

<sub>Sources: t1:T2-09, t2:T2-05, t4:T4-01, t1:T2-10 (unverified, PATH part)</sub>

### BX-08 (P1, connect-host, docs) — No document gives a host-specific procedure to register `arcavex mcp serve` with Claude Code, Claude Desktop or Codex; the skill tells the assistant to 'tell the user how to connect the engine' with nothing to cite

**Evidence.** README.md:321 "Wire it into an MCP client (e.g. Claude Desktop) as a stdio server running `arcavex mcp serve`." is the only host-facing sentence in the repo; docs/cli.md:440-451 lists only `serve`/`tools` and links back. grep -rni 'claude mcp add|codex mcp add|claude_desktop_config|mcpServers|mcp_servers|\.mcp\.json' over README.md, docs/**, skills/**, examples/** -> zero hits (only third-party mcp SDK source in .venv); docs/install.md 'Next steps' (:142-146) has no MCP handoff; docs/packaged-install.md and quick-start.md have zero MCP mentions. SKILL.md:38 "**Neither?** Say so and tell the user how to connect the engine" — grep of the whole skill (repo, bundled and installed copies) for `mcp serve|claude mcp|mcp add|handshake|stdio|connect` returns only that line; SKILL.md:36 presupposes the arcavex_* tools are already present. packaging/README.md:193-195 mentions an mcpb bundle for Claude Desktop as a maintainer note (no manifest shipped). Because the documented install leaves `arcavex` off PATH, any host entry must use the venv's absolute exe path, which no doc states. Verifier reproduced the path-escaping trap: single-backslash Windows path in claude_desktop_config JSON -> `JSONDecodeError: Invalid \escape`; in codex TOML -> `TOMLDecodeError: Invalid hex value`. Claude Code specifics: `claude mcp add -s project arcavex -- <exe> mcp serve` works but `claude mcp list/get` show "⏸ Pending approval (run `claude` to approve)" until a person opens `claude` in that folder; no Arcavex doc mentions scope or approval (Claude Code 2.1.261; `-s project` was the tracer's choice, default is local). The MCP resources served are only the six skill:// files — no connect guide in-band. Server itself starts and serves correctly from an absolute path.

**Impact.** The assistant must invent host command, config-file location, absolute exe path and Windows escaping from general knowledge; a non-technical person gets 'connect the engine' with no steps, or a 'Pending approval' status that looks like failure. Docs gap, not a broken server.

**Fix.** Add a 'Connect your assistant' section with copy-paste `claude mcp add -s user arcavex -- <abs exe> mcp serve` (plus the Pending-approval note), the claude_desktop_config.json `mcpServers` block with doubled backslashes and quit/reopen, and the `codex mcp add` / [mcp_servers.arcavex] TOML form — and mirror a short version into the skill. (`README.md:321 (replace with a "Connect your assistant" subsection after the skill-install paragraph ~:35-41); skills/arcavex-design-studio/references/engine-and-loop.md:3-17 ("Finding the engine") with SKILL.md:38 pointing at it; docs/install.md:142 link`)

**Status: fixed.** `0c0bdd8` — `docs/connect-your-assistant.md` and a connecting section in the CLI reference with `--list`/`--print` transcripts; `67079d1` — a Connecting block in the skill

<sub>Sources: t1:T2-08, t2:T2-07, t3:T3-01, t7:T7-03, t3:T3-08</sub>

### BX-09 (P1, connect-host, user-ux) — Arcavex has a host-aware installer for the skill (`skill install`) but no command that registers the MCP server with a host, and `skill install` ends without mentioning the engine connection

**Evidence.** `arcavex mcp --help` -> only `serve` and `tools` (cli.py:1730 `@mcp_app.command("serve")`, :1742 `"tools"`); src/arcavex/clients/ has no MCP registration module; `arcavex --help` lists no install/setup/register. `arcavex skill install --list` shows it already knows per-host paths (Claude Code C:\Users\<u>\.claude\skills\…, Codex/ChatGPT C:\Users\<u>\.agents\skills\…). `arcavex skill install --path <dir>` ends: "Installed arcavex-design-studio to 1 location(s): ... Restart the assistant to pick it up." — no mention of MCP or a next step. README.md:28-33 'Then install the bundled design skill so an AI assistant knows the workflow' + `arcavex skill install # Claude Code + Codex/ChatGPT` — the section stops there. SKILL.md:38 instructs 'tell the user how to connect the engine' with no how. For no-shell hosts (Claude Desktop, ChatGPT desktop — the latter explicitly a `skill install` target at README.md:39-40) MCP is the only engine path; ChatGPT desktop cannot run local stdio servers at all, so the skill install gives it a manual for an engine it cannot reach. In shell hosts SKILL.md:31-33 Step 0 routes the assistant to the CLI, so not blocked there.

**Impact.** A person following 'Install, and teach your assistant to use it' runs `skill install` and believes setup is complete; in a no-shell host the assistant then loads a skill whose Step 0 tells it to explain a connection it has no text for, bouncing the person to hand-editing JSON/TOML.

**Fix.** Add `arcavex mcp install` that writes the correctly escaped host config (or shells out to `claude mcp add`/`codex mcp add`) using its own absolute exe path, and have `skill install` print 'Next: arcavex mcp install'. (`product: `arcavex mcp install [--target claude-code|claude-desktop|codex] [--list]` mirroring `skill install`, with `skill install` printing it as the next step; minimum doc fallback README.md:321 (BX-08)`)

**Status: fixed.** `6f508ff` — `arcavex mcp install`: Claude Code via `claude mcp add -s user`, Claude Desktop JSON edited in place with a `.bak`, Codex TOML; `--list`, `--print`, `--force`, `--command`; ARC-MCP-001…004; 51 tests

<sub>Sources: t3:T3-02</sub>

### BX-10 (P1, connect-host, docs) — docs/cli.md claims to cover every subcommand but has no `skill`, `editor` or `desktop` section, and no doc says to restart Claude Code/Codex after `arcavex skill install`

**Evidence.** docs/cli.md:3-4 "Every Arcavex capability is a subcommand ... This page is the command-by-command reference"; the command index (:30-53) lists render…ext only; `grep -n -i skill docs/cli.md docs/install.md docs/quick-start.md` -> nothing; `grep -E '^## (editor|desktop|skill)' docs/cli.md` -> nothing. `arcavex --help` shows "editor  Semantic project editing: apply, undo, redo, history.", "skill  Install the bundled design skill into an AI assistant.", "desktop  Desktop engine compatibility commands."; `skill install --help` has --target/-t, --path, --force, --project, --list, --json. README.md:33-34 is the only place documenting `skill install` (one comment line) and README.md:29-45 contains no restart instruction; grep -i 'restart|pick it up|reload|new session' over README.md, docs/*.md, skills/ -> only docs/testing.md:26 (unrelated). The restart hint exists only in runtime output: src/arcavex/clients/cli.py:2101 console.print("Restart the assistant to pick it up."). engine-and-loop.md:112 says to prefer the editor transaction over template_patch but its CLI↔MCP table (:32-43) has no editor row, and README.md:100 promises 'Every command, its flags, and a verified example'.

**Impact.** The reference page cannot be used to look up the second command the README tells a new user to run, nor the shell form of the editor the skill tells the assistant to prefer; an assistant planning from the docs does not know the new skill is invisible to the running session until a restart, so it proceeds without it.

**Fix.** Document `skill`, `editor` and `desktop` in docs/cli.md and add 'Restart Claude Code / start a new Codex session so the skill is picked up' after `arcavex skill install` in the README. (`docs/cli.md (add `## skill`, `## editor`, `## desktop` sections and index rows); README.md:29-41 (one-line restart note)`)

**Status: fixed.** `a7c6385` — `editor`, `skill`, `desktop` in the CLI reference; `f640a53`, `d76dd5b` — restart the host after `skill install`

<sub>Sources: t2:T2-06, t1:T2-11 (unverified), t1:T2-10 (unverified, restart part)</sub>

### BX-11 (P1, connect-host, docs) — Docs state the MCP catalog has 25 (or 24) tools mirroring the CLI; the server exposes 46, and 19 of them (engine_handshake, project_*, layer_tree, hit_test, editor_*) appear in no user-facing doc

**Evidence.** README.md:322 "The catalog (25 tools) mirrors the CLI: ..."; docs/cli.md:447 "Print the 25-tool catalog"; docs/architecture.md:165-166 "adds no exclusive capability. Every one of its 25 tools is a thin wrapper over exactly one kernel.api facade method"; README.md:162 "| MCP tools discovered | 24 |" (historical run table). Observed by four tracers/verifiers: `arcavex mcp tools --json` and tools/list via proxy -> 46 (33 `arcavex_*` + 13 unprefixed). Expanding README.md:322's own shorthand yields 27 names (all present), so the paragraph does not match its own list either; the undocumented delta is 19: engine_handshake, arcavex_template_detach, project_snapshot/validate/preview, layer_tree, hit_test, project_ui_metadata[_set], project_policy[_set], project_proposal_list/approve/reject, arcavex_editor_apply/apply_authorized/undo/redo/history. tests/mcp_sessions/test_schema_parity.py:120 already asserts `len(catalog) == 46`, so only the prose is stale; no test checks the documented count. engine-and-loop.md:72-129 relies on editor transactions, project_snapshot and layer_tree that the README's authoritative-sounding list omits.

**Impact.** An assistant that reads the docs to learn the surface expects 25 tools and a specific list, then meets 46 with 21 unexplained; the 'no exclusive capability' parity story no longer describes what the host sees, and the tools the skill tells it to prefer are absent from the README.

**Fix.** Regenerate the count and tool list from `arcavex mcp tools --json` (listing the authoring and desktop/editor families separately) and assert the documented count against the catalog in the schema-parity test. (`README.md:322-329 (with README.md:162, docs/cli.md:447, docs/architecture.md:166); tests/mcp_sessions/test_schema_parity.py`)

**Status: fixed.** `f640a53` — tool families instead of counts; `3f9c587` — a test fails on any front-door document stating a tool count

<sub>Sources: t2:T2-04, t3:T3-03, t1:T2-12 (unverified)</sub>

### BX-12 (P1, learn, docs) — README's opening example, quick-start steps 1-3/5, cli.md and packaged-install.md render files that do not exist (examples/hello-poster, poster.yaml, event.yaml), while the quick start claims 'every command below is a real Arcavex command run against the shipped examples'

**Evidence.** README.md:15-16 `arcavex render examples/hello-poster/template.yaml --data examples/hello-poster/data.yaml --format square -o out.png`; docs/quick-start.md:3-4 "Every command below is a real Arcavex command run against the shipped examples; the output shown is what it actually prints."; quick-start.md:19-20, 28-31, 40-44, 51, 66-67, 99-105 `arcavex render poster.yaml --data event.yaml ...`; docs/cli.md:80-91, 220, 256-257, 301 and docs/packaged-install.md:108-109 same files. `ls examples` -> extensions, future-archive-poster, graphic-style-lab; `find` for hello-poster*, poster.yaml, event.yaml, hello.png (excluding .git/.venv) -> nothing. Running README:15 -> "ERROR ARC-TPL-001 File not found: examples\hello-poster\template.yaml ... hint: Check the path passed on the command line." exit 3; quick-start step 1 -> "ARC-TPL-001 File not found: poster.yaml" exit 3. commit a5e09d8 "chore!: remove five example posters ... ~40 docs referenced them" deleted examples/hello-poster (which was itself template.yaml/data.yaml, never poster.yaml/event.yaml). Stale transcripts: quick-start.md:30 "inferred: output=hello-poster.square.png" vs cli.md:90 "poster.square.png" for the same command; engine really prints `poster.square.png`. git grep still hits README (2), quick-start (14), cli.md (8), packaged-install (2), diagnostics.md (2), testing.md (1), backlog.md (2). `arcavex template new` + render works ("Created card (render with --format square)" / "Rendered card.png") but is only mentioned at quick-start.md:183. Verifier severities: t2 P0 (no shipped path to a green first render from the docs), t1/t4 P1 (loud error, substitute exists).

**Impact.** The very first command an assistant copies from the README fails before any install problem is reached; steps 1, 2, 3 and 5 of the '10-minute' quick start cannot be run; the assistant either invents files or abandons the quick start, and the contradictory inferred names show the transcripts were never regenerated.

**Fix.** Point the README opener and quick-start steps 1-5 at something that ships (`arcavex template new ./card && arcavex render ./card --format square -o out.png`, or a restored minimal hello-poster) and regenerate every transcript from a real run. (`README.md:14-17 and docs/quick-start.md §1-§3/§5 (lines 14-70, 99-105); mirror docs/cli.md:80-91,220,256,301 and docs/packaged-install.md:108`)

**Status: fixed.** `7249c6d` — hello poster restored; front-door docs repointed; a test reads them like a newcomer

<sub>Sources: t1:T2-03, t1:T2-04, t2:T2-01, t4:T4-02</sub>

### BX-13 (P1, learn, docs) — Quick start shows fabricated outputs against the reference poster: format `a4` (template declares four formats, no a4), '5 formats × 2 locales', an `inferred: data_overlay=data.fa.yaml` line that never occurs, and an 'IPEN' example that does not exist

**Evidence.** docs/quick-start.md:107-110 `arcavex render examples/future-archive-poster/template.yaml -d .../data/en.yaml -f a4 --locale fa -o poster.pdf` / "inferred: data_overlay=data.fa.yaml / Rendered poster.pdf"; :160-162 `template inspect ... --resolved --format a4 --locale fa` / "resolved format=a4 ..."; :188-189 "5 formats × 2 locales from one node tree". template.yaml declares formats only at :24 square, :26 portrait, :54 story, :108 landscape; README.md:134-135 lists the same four. Observed: both a4 commands -> "ERROR ARC-TPL-022 Unknown format 'a4' ... hint: Available formats: landscape, portrait, square, story" exit 1; `-f portrait` (after ext enable) renders a valid 2.5 MB %PDF-1.4 with MediaBox/TrimBox — so PDF works, only the name is wrong. quick-start.md:73 "The bilingual IPEN example declares `en` and `fa`", :79 `-o ipen-fa.png`, packaged-install.md:111 `-o ipen.pdf`: no IPEN example exists. quick-start.md:78-81 with `--data data/en.yaml --locale fa` actually prints "WARNING ARC-TPL-102 Locale 'fa' was applied but supplies no text of its own ... hint: Add 'locales.fa.data', or a sibling '<data>.fa.yaml'" — data/ holds en.yaml, fa.yaml, stress-*.yaml, no en.fa.yaml, so the documented data_overlay inference does not happen. Line introduced in commit 858572f "docs: task 12 consolidation".

**Impact.** The PDF/print step of the quick start fails and the assistant may conclude A4/PDF is unsupported; the locale step yields English text under RTL rules plus a warning the doc never mentions; 'IPEN' sends the assistant looking for an example that is not in the repo.

**Fix.** Use a declared format (`-f portrait`), `--data data/fa.yaml --locale fa`, rename IPEN to Future Archive, change '5 formats' to four, and paste real output. (`docs/quick-start.md:73-81, 107-110, 160-162, 188-189; docs/packaged-install.md:110-112`)

**Status: fixed.** `a7c6385` — quick start rewritten around the real example; every self-contained command runs in a test

<sub>Sources: t1:T2-06, t1:T2-07 (unverified), t2:T2-10 (unverified)</sub>

### BX-14 (P1, learn, bug) — MCP tools silently accept and ignore unknown argument keys (format/formats on template_new, dpi on project_create, scale on render), returning ok:true with empty diagnostics

**Evidence.** Verifier reproduced: `arcavex_template_new {target, format:"poster"}` and `{zzz_bogus:1}` -> ok:true, "format":"square", no diagnostic; `arcavex_project_create {..., dpi:300}` -> ok, `project_snapshot` "dpi": null; `arcavex_render {format:"story", scale:2}` -> ok, PNG IHDR 1080x1920 (unchanged) while `dpi:300` -> 3375x6000. Cause: FastMCP-generated pydantic arg models use the default extra='ignore' (mcp 1.29.0 func_metadata.py:64 `ConfigDict(arbitrary_types_allowed=True)`) and the published inputSchema sets no additionalProperties:false. Refuted detail: `dpi` IS declared in the inputSchema of arcavex_render and arcavex_project_render (integer|null); it is only absent from the one-line descriptions and from the skill (zero mentions of dpi in skills/**/*.md). Contrasts with the engine's template philosophy where unknown fields are rejected (ARC-TPL-051).

**Impact.** An assistant cannot tell an honoured option from an ignored one; it believed it had asked for a poster format and a 300-dpi project and could tell the person so. An assistant that follows the schema would not send these keys, but one that guesses gets an affirmative answer for an unhonoured request.

**Fix.** Reject unknown argument keys with a coded diagnostic listing the accepted fields (extra='forbid' / additionalProperties:false) and mention `dpi` in the render tool descriptions and skill. (`src/arcavex/clients/mcp_server.py build_mcp_server tool registration (~line 645); arcavex_render/arcavex_project_render docstrings and SKILL.md for dpi`)

**Status: fixed.** `af8ab60` — an unknown key is refused before dispatch with `ARC-MCP-010`, a near-miss suggestion, and no side effect; every tool schema now sets `additionalProperties: false`

<sub>Sources: t5:T5-04</sub>

### BX-15 (P1, design, docs) — Skill's Command↔MCP map names a CLI command `project render` that does not exist (project mode is `arcavex render` with no template / `--project DIR`)

**Evidence.** skills/arcavex-design-studio/references/engine-and-loop.md:41 "| Recorded, reproducible render | `project render` | `arcavex_project_render` |" (identical in the bundled copy). `arcavex project render --help` -> "Usage: arcavex project [OPTIONS] COMMAND [ARGS]... No such command 'render'." exit 2; `arcavex project --help` lists only new, clone, set-status, upgrade. `arcavex render --help`: "[template] PATH Template YAML file. Omit to render the current project (project mode).", "--project PATH Project directory (project mode)", "--record ... always on in project mode". The MCP cell (`arcavex_project_render`) is correct; docs/cli.md:62 documents the real form.

**Impact.** An assistant following the CLI cell gets exit 2 and must guess the real form — a retry loop before finding `arcavex render --project`.

**Fix.** Change the CLI cell to `render` (no template) / `render --project DIR`, matching `arcavex render --help`. (`skills/arcavex-design-studio/references/engine-and-loop.md:41 (CLI cell)`)

**Status: fixed.** `67079d1`

<sub>Sources: t7:T7-02</sub>

### BX-16 (P1, design, docs) — Skill's capability table and Command↔MCP map omit every MCP tool an MCP-only assistant needs to start from nothing or manage assets/runs (template_new, project_create, data_set/import, asset_add/annotate, run_list/diff/rerun, template_list/publish/detach, render, render_record)

**Evidence.** SKILL.md:44 "| MCP only | Author, validate, preview, render, localize | Author extensions, install fonts, preprocess images |"; engine-and-loop.md:32-43 map lists only arcavex_template_inspect/_patch/_validate, arcavex_render_preview, arcavex_layout_inspect, arcavex_effects_list/_style_list/_font_list, arcavex_diagnostic_explain, arcavex_project_render plus two 'shell only' rows. `arcavex mcp tools` also offers arcavex_template_new ("Scaffold a minimal renderable template directory to start a new design from."), arcavex_project_create, arcavex_data_set ("Set a single value at a dotted 'keypath' in the project's data"), arcavex_data_import, arcavex_asset_add ("Ingest an image into the workspace content-addressed store"), arcavex_asset_annotate ("facing/focal_point/tags"), arcavex_run_list/_diff/_rerun, arcavex_template_list/_publish/_detach, arcavex_style_inspect, arcavex_render, arcavex_render_record. grep of all six skill files for template_new|project_create|data_set|asset_add|asset_annotate|run_list|rerun -> zero hits. SKILL.md Step 5 'Author the template' names no tool that creates one (template_patch edits an existing file). Verifier called arcavex_template_new over MCP -> ok:true, files created. Refuted portion: editor_apply/undo/redo/history ARE documented at engine-and-loop.md:71-115 (just not in the map table).

**Impact.** An assistant with MCP only does not learn it can scaffold a template, create a project, set data, ingest/annotate assets or replay runs; it may hand-write YAML or wrongly tell the person a step needs a shell.

**Fix.** Extend the map with rows for start-from-nothing (template_new, project_create, data_set/import), assets (asset_add/annotate), runs (run_list/diff/rerun) and the editor, and refine the MCP-only 'cannot' cell. (`skills/arcavex-design-studio/references/engine-and-loop.md:30-43 (Command↔MCP map) and SKILL.md:41-44`)

**Status: fixed.** `67079d1`, `8db4fae` — every registered authoring tool is named and the MCP-only row corrected; `b71f8f5` pins the skill's vocabulary to the engine's registries

<sub>Sources: t7:T7-04</sub>

### BX-17 (P1, design, docs) — The template vocabulary is documented only in Python source: template-schema.md never lists the 13 `style:` keys, and shape-generator params (starburst points/inner_ratio, speech_bubble, qr_code) are exposed nowhere — not in docs, examples, effects_list, the skill, or the ARC-FX-912 hint that cites a 'documented schema'

**Evidence.** docs/template-schema.md:133-136 says only "Paint properties (`opacity`, `color`, `font_size`, …) live in `style:`"; :113 and :382 name the generators but no params and :382 points to examples/graphic-style-lab, where `grep -rn generator examples/ --include=*.yaml` -> 0 hits. Source of truth: compiler.py:111-115 `_STYLE_KEYS = frozenset({fill, stroke, stroke_width, color, corner_radius, opacity, font, font_size, font_weight, italic, align, direction, letter_spacing})`; shapes.py:44-45 `points: int = Field(default=12, ge=3, le=120)` / `inner_ratio: float = Field(default=0.5, gt=0.0, lt=1.0)`; SpeechBubbleParams :86-90, QrCodeParams :159-160. Observed: `arcavex_effects_list`/`effects list` contain no generators (`effects inspect starburst` -> 'unknown effect'); all six skill:// resources -> 0 matches for generator|starburst|inner_ratio; ARC-FX-912 "invalid params: bogus: Extra inputs are not permitted / hint: Check each parameter's name, type, and range for this generator."; `explain ARC-FX-912` -> "Check each parameter against the generator's documented schema" — no such schema exists. ARC-TPL-036's hint "or a 'generator:' (starburst, ...)" reads as a shape value and `shape: generator:starburst` is itself rejected (separate wrong turn). Refuted portion: style keys need no trial-and-error — the first ARC-TPL-051 error lists all 13 valid style fields (CLI and MCP). Scaffold README (unverified T5-12) points to CLI commands and 'the top-level project README' for repeat/split layout; no template-authoring reference is served as an MCP resource.

**Impact.** To draw a stroked shape, italic text or a starburst badge the shell assistant had to grep Python source; the MCP-only assistant shipped its starburst on defaults because generator params are undiscoverable without a shell, and image nodes/repeat/masks/format patches were never learnable from what MCP serves.

**Fix.** Add style-key and generator-param tables to template-schema.md, make the ARC-FX-912 hint enumerate valid parameter names, and expose generators with schemas over MCP. (`docs/template-schema.md (Nodes section ~:129-136 for a style-key table; generator paragraph :382 for a params table); ARC-FX-912 hint at src/arcavex/services/template/compiler.py:2271; MCP: extend arcavex_effects_list or add arcavex_generator_list`)

**Status: fixed.** `48d53cb` — style, paragraph and generator tables in template-schema.md, pinned by `6875741`; `dcc78db` — `arcavex shapes list` and `arcavex_shape_list`, and ARC-FX-912 now enumerates a generator's valid parameters with their defaults

<sub>Sources: t5:T5-07, t4:T4-04, t5:T5-12 (unverified)</sub>

### BX-18 (P1, design, ai-ux) — An inset frame is expressible (padded vstack + fill child) but nothing points there: opposite-edge anchors are refused (ARC-LAY-031/032), `fill` silently ignores anchor offsets and overshoots the parent, percent offsets are refused (ARC-LAY-012), and none of the hints, template-schema.md or the skill mention the padding idiom

**Evidence.** Verifier reproduced all three diagnostics verbatim: four-edge anchors, no size -> ARC-LAY-032 "has 'constraints' but no 'size'" hint "Add 'size: {w: ..., h: ...}' — each of fixed, a %, 'fill', or {aspect}"; plus size fill -> ARC-LAY-031 "over-constrained on the horizontal axis: left, right" hint "Keep exactly one horizontal anchor; size comes from the size spec."; offset '+30%' -> ARC-LAY-012 hint "Offsets look like '+20px', '+20pt', or '-6mm'." With anchor top+40/left+40 + size fill, layout inspect bounds_px [40,40,1080,1080] (square) / [40,40,1080,1920] (story), overflow None, warnings [] — solver.py _axis_size `if spec.mode == "fill": return basis`. Refuting 'cannot be expressed': a `group` with `layout: vstack`, `padding: 40px`, child size fill/fill validates and yields [40,40,1000,1000] / [40,40,1000,1840] — an exact inset once for both formats. But docs/template-schema.md lists `padding` only as a stack property (:110,126,241) with no inset/frame idiom; ARC-LAY-031/032 hints and their diagnostics docs never mention padding; SKILL.md:150-151 and art-direction.md:49 say 'Write the margin down' without a construct. Tracer's transcript shows three LAY-031/032 rounds and three LAY-012 rounds before abandoning the device for a crossed-corner bar frame.

**Impact.** The most basic poster device — a plain inset border — costs an assistant multiple validation rounds and is then abandoned, because the hints steer toward single-anchor + size and never toward the working idiom; `fill` overshooting silently produces a clipped frame with no warning.

**Fix.** Make the ARC-LAY-031/032 hints and template-schema.md name the padded-stack inset idiom (or let `fill` mean parent-minus-offset / accept stretch anchors), and warn when a fill-sized node overshoots its parent. (`src/arcavex/builtin/layout_anchors/solver.py (_require_single ARC-LAY-031 hint ~line 665, and the fill overshoot path in _axis_size); docs/template-schema.md 'Sizes'`)

**Status: fixed.** `39ce51a` — the ARC-LAY-031/032 hints name the span and inset idioms, and a new ARC-LAY-033 warns when a fill-sized node overshoots its parent; `35b6219` — ARC-LAY-012 explains why a percent offset is refused and what to write instead

<sub>Sources: t5:T5-06</sub>

### BX-19 (P1, design, bug) — Scaffold placeholder copy ('A scaffolded card') is copied verbatim into project data by project_create and prints on the project render, while render_preview of the same template shows different (preview_data) copy — with no diagnostic

**Evidence.** Verifier reproduced end-to-end over MCP: template_new writes `tpl/data.yaml` = `title: "Hello from Arcavex"` / `subtitle: "A scaffolded card"` (services/authoring.py:194-195); project_create copies it verbatim to `proj/data/proj.yaml` (services/projects.py:210-218: "A template's own data.yaml is real content; preview_data is a thumbnail of it"); after `data_set title="Golden Crust"` the data file still holds `subtitle: "A scaffolded card"`; project_render -> ok:true, diagnostics [] and the PNG visibly shows "Golden Crust / A scaffolded card". render_preview on the bare template uses preview_data and shows "My Card / Edit data.yaml to change me" instead, so the template's `default(...)` is dead code for project renders. Tracer's own template default ('NEIGHBOURHOOD BAKERY') was its own patch; the stock default is 'Edit data.yaml to change me'.

**Impact.** Previews look right while the project render silently carries placeholder copy; a non-technical person could print 'A scaffolded card' on a shop window. Visible on the render so catchable, but nothing in tool output flags it and the preview path suggests the default is in effect.

**Fix.** Stop shipping placeholder values that read like real copy in the scaffold's data.yaml (copy only required variables into the project) or emit an ARC-PRJ warning when project data still equals scaffold defaults. (`src/arcavex/services/authoring.py:194-195 (scaffold data.yaml placeholder) and/or src/arcavex/services/projects.py:210-218 (project_create copy)`)

**Status: fixed.** `7150cb6` — ARC-PRJ-015 names every variable whose value is still the scaffold's placeholder, at render, preview and validate; the scaffold's own data now reads as placeholders

<sub>Sources: t5:T5-05</sub>

### BX-20 (P2, discover, user-ux) — README leads a newcomer through engine internals, extension authoring and encoder details — and two failing commands — before the first beginner pointer at line 72, and the one working from-scratch path (`template new`) is buried behind a tutorials index that sends the reader back to the failing quick start

**Evidence.** unverified. README.md:3 "Local-first, headless, deterministic, template-driven rendering engine built on skia-python."; :15-16 hello-poster render (BX-12); :22 `uv pip install arcavex` (BX-01); :48-52 `ext scaffold effect ./my-effect --name grain-warp` loop before any working render; :58-70 output extensions, --quality, --lossless, PDF bleed boxes, filename inference; :72-73 "**New here?** Install → Quick start → ... → Tutorials" — the first beginner pointer. docs/tutorials/README.md:12-13 "New to Arcavex? Do the quick start first — it renders the shipped examples in about ten minutes" (steps 1-5 fail). building-a-template.md:13-14, 30-32 `template new ./card` / `render ./card --format square -o card.png` — observed working: "Created card (render with --format square)" / "inferred: data=preview_data / Rendered card.png" (20,491 bytes); `doctor` all ok. The 'Install, and teach your assistant' section (19-56) never mentions registering the MCP server.

**Impact.** An assistant reading top-down executes two failing commands and reads extension-authoring and encoder details before reaching the only path that works; the one section aimed at assistants stops at skill install and omits connect-host.

**Fix.** Put a 4-line 'Start here' block at the top (clone → `uv venv && uv pip install -e .` → `arcavex doctor` → `skill install` + MCP registration → `template new ./card && render ./card --format square -o card.png`) and move the ext loop and encoder details below the fold. (`README.md:1-73; docs/tutorials/README.md:12-13`)

**Status: fixed.** `f640a53` — a 'Get it working' block an assistant can run top to bottom, before anything else

<sub>Sources: t1:T2-14 (unverified), t1:T2-17 (unverified)</sub>

### BX-21 (P2, discover, docs) — Skill Step 0's shell fallback `python -m arcavex.clients.cli` only works when `python` is the engine's own interpreter, 'look for a standalone binary' gives no location, and `python -m arcavex` fails because the package has no __main__

**Evidence.** SKILL.md:33-34 "Try `arcavex --version`. If it is not on PATH, try `python -m arcavex.clients.cli --version`, then look for a standalone binary."; engine-and-loop.md:8-9 same. Observed from Git Bash: `arcavex --version` -> command not found (127); system Python 3.14 `-m arcavex.clients.cli` -> "ModuleNotFoundError: No module named 'arcavex'"; engine venv python -> "arcavex 0.1.0"; engine venv `python -m arcavex --version` -> "No module named arcavex.__main__; 'arcavex' is a package and cannot be directly executed" exit 1. No `__main__.py` in src/arcavex or either venv's site-packages. No path for the 'standalone binary' in the skill, install.md, packaged-install.md or README; the only hints are in the desktop design spec and apps/desktop supervisor.rs ('binaries/engine-lock.json'). `python -m arcavex` is not documented — it is a natural guess an assistant without the loaded skill will make.

**Impact.** An assistant on a shell without the engine on PATH gets two dead ends before falling through to the MCP check and may conclude no engine is present; on a machine where the engine came with the desktop app it does not know where the bundled binary lives.

**Fix.** Name the engine's likely locations in Step 0 (`.venv\Scripts\arcavex.exe`, uv tool bin dir, desktop sidecar) and add `src/arcavex/__main__.py` delegating to `arcavex.clients.cli:main` so `python -m arcavex` works. (`skills/arcavex-design-studio/SKILL.md:33-34 and references/engine-and-loop.md:8-9; src/arcavex/__main__.py (new)`)

**Status: fixed.** `915c042` — `python -m arcavex`; `67079d1` — Step 0 names the engine's likely locations, including the desktop's bundled sidecar

<sub>Sources: t7:T7-06, t1:T2-16 (unverified)</sub>

### BX-22 (P2, discover, docs) — Nothing beginner-facing (docs or skill) describes Arcavex Desktop as the person's live viewer/editor — that the canvas refreshes and the activity panel shows an assistant's edits — and the skill never mentions the desktop app exists

**Evidence.** Only 'desktop' in the skill: engine-and-loop.md:72 "a person at the desktop and an assistant over MCP" (generic); SKILL.md:41-44 Step 0 table has only 'Shell (± MCP)' and 'MCP only' rows, though the engine ships `arcavex desktop handshake` and MCP `engine_handshake` with desktop.* capabilities. docs/desktop/editor.md:103-104 "The activity stream reports edits this window did not make, so an assistant working in the same project is visible rather than mysterious" and README.md:82-85 (revisions, shared undo, conflicts) are the only collaboration prose — written in lock/refusal terms. The behaviour exists in code (apps/desktop/src/features/projects/projectQueries.ts:4-5 "a change made by an AI client or the CLI refreshes the workbench"; ActivityPanel.tsx labels the actor 'External') but nowhere in a user doc; quick-start, install.md, tutorials never mention the desktop. Caveat: apps/desktop/CHANGELOG.md:11-13 says the app is 'not yet published as a desktop-v* release', so any skill row must be worded to match.

**Impact.** An assistant cannot tell a non-technical person 'open your project in the window; when I change something the canvas refreshes and the change appears in the activity list' — the no-shell way to see and edit the design is invisible to it.

**Fix.** Add a plain-language 'Working with your assistant' paragraph to editor.md/README and a 'Desktop app (when released)' row to the skill's Step 0 table. (`docs/desktop/editor.md (plain-language 'Working with your assistant' intro); README.md "## Arcavex Desktop"; skills/arcavex-design-studio/SKILL.md:41-44`)

**Status: fixed.** `f640a53` in the README and `8db4fae` as a Desktop row in the skill's Step 0; the editor branch adds the plain-language paragraph to `docs/desktop/editor.md`

<sub>Sources: t6:T6-06, t7:T7-08</sub>

### BX-23 (P2, install, docs) — packaged-install.md's 'captured verbatim' transcript pins typer==0.27.0, which pyproject's own bound (<0.27) forbids and no install produces

**Evidence.** unverified. docs/packaged-install.md:43 `+ typer==0.27.0`; pyproject.toml:32 `"typer>=0.26,<0.27",  # 0.26.8 — pre-1.0, minor bumps are breaking`; observed `uv pip install -e ".[dev]"` and `uv tool install` both installed `+ typer==0.26.8`.

**Impact.** A reader checking their install against the transcript the doc calls proof sees a mismatch.

**Fix.** Re-capture the packaged-install transcript from the current lockfile or drop exact-version lines. (`docs/packaged-install.md:41-44`)

**Status: fixed.** `787e74e` — transcript re-captured against the shipped examples; wheel and dev tree verified byte-identical

<sub>Sources: t2:T2-09 (unverified)</sub>

### BX-24 (P2, connect-host, user-ux) — `arcavex skill install --list` ellipsizes destination paths in terminals narrower than ~108 columns, hiding the final directory name

**Evidence.** At default width and COLUMNS=80 (two tracers + verifier): "Claude Code  C:\Users\payam\.claude\skills\…  not installed / Codex / ChatGPT (Agent Skills  C:\Users\payam\.agents\skills\…  not installed / standard)"; at COLUMNS=120 and via `--json` the full paths (...\arcavex-design-studio) appear. Cause: src/arcavex/clients/cli.py ~2086-2091 `Table(box=None, pad_edge=False)` / `table.add_column("path")` with no no_wrap/overflow setting. The non-list install prints full paths, so only the preview is affected; the flag's help text is "Show every destination without writing anything."

**Impact.** The flag whose purpose is to preview destinations hides where files will land in a standard terminal; the user must know to add --json.

**Fix.** Print destinations one per line (label then full path) or set the path column to fold/no-wrap instead of ellipsis. (`src/arcavex/clients/cli.py `_print_skill_report` (`table.add_column("path")` ~line 2088)`)

**Status: fixed.** `7130563` — one block per destination, the path whole on its own line

<sub>Sources: t2:T2-08, t7:T7-09 (unverified duplicate)</sub>

### BX-25 (P2, connect-host, bug) — Every `arcavex mcp serve` start and `mcp tools` run writes a pydantic_settings IncompleteFieldDefinitionWarning to stderr

**Evidence.** stderr (verified on `mcp tools --json` and on `mcp serve` initialize; not emitted by doctor/effects list): "...pydantic_settings\sources\utils.py:47: IncompleteFieldDefinitionWarning: Field 'lifespan' has an incomplete definition: its annotation contains an unresolved forward reference ... Call `model_rebuild()` on the model where the field is defined ... warnings.warn(". Source is the upstream FastMCP Settings field (mcp/server/fastmcp/server.py:124) with pydantic_settings 2.15.0 + mcp 1.29.0; no pydantic-settings pin and no warnings filter in the repo. stdout stays valid JSON; bash `> f 2>&1` or PowerShell `2>&1 > f` yields a non-JSON file (POSIX `2>&1 > f` leaves the file valid).

**Impact.** A host's MCP server log opens with a Python warning about a broken field definition — the first thing a person sees when checking whether the connection worked — and an assistant merging streams gets a file that does not parse. No functional failure.

**Fix.** Filter or fix the warning at server start (warnings filter for that category, model_rebuild, or a pydantic-settings pin) and assert empty stderr on `mcp serve` initialize. (`src/arcavex/clients/mcp_server.py (around line 643 / import at :27); test under tests/mcp_sessions/ asserting empty stderr on initialize`)

**Status: fixed.** `f23cacd` silenced the import and `bccbcb3` the construction, which is the one every `mcp serve` actually meets. This was recorded here as fixed after the first commit on the strength of a test that only imported the module; the agent working on the MCP surface caught the half that was still printing

<sub>Sources: t3:T3-07, t7:T7-10 (unverified duplicate)</sub>

### BX-26 (P2, connect-host, bug) — MCP `initialize` reports serverInfo.version 1.29.0 (the mcp SDK's package version) instead of the engine's 0.1.0

**Evidence.** initialize response `"serverInfo":{"name":"arcavex","version":"1.29.0"}`; `arcavex --version` -> arcavex 0.1.0; engine venv mcp 1.29.0. Cause: mcp_server.py:643 `FastMCP("arcavex", instructions=_INSTRUCTIONS)` passes no version and the lowlevel server defaults to `pkg_version("mcp")`. Note the tracer's fix sketch `FastMCP(..., version=...)` is invalid — FastMCP.__init__ in mcp 1.29.0 has no `version` kwarg; set it on the underlying lowlevel server. No test asserts serverInfo.version.

**Impact.** Host UIs and logs show a version matching nothing in the docs or `arcavex doctor`, so a person reporting a problem gives the wrong version. Cosmetic.

**Fix.** Set the engine version on the underlying lowlevel MCP server (e.g. `server._mcp_server.version = arcavex.__version__`) and assert it in the schema-parity test. (`src/arcavex/clients/mcp_server.py:643 (build_mcp_server) plus an assertion in tests/mcp_sessions/`)

**Status: fixed.** `f23cacd` — `serverInfo.version` is the engine's

<sub>Sources: t3:T3-06</sub>

### BX-27 (P2, connect-host, ai-ux) — 13 of 46 MCP tools lack the `arcavex_` prefix, carry desktop-internal descriptions, lead the list (engine_handshake first), and are explained nowhere for an assistant

**Evidence.** Unprefixed: engine_handshake, project_snapshot, project_validate, project_preview, layer_tree, hit_test, project_ui_metadata[_set], project_policy[_set], project_proposal_list/approve/reject (mcp_server.py:585-609 under the `# ---- desktop` section). Descriptions: "project_preview — Render structured per-target project preview reports for desktop viewers.", "project_proposal_approve — Authorize a current proposal without claiming its command was applied.", "hit_test — Return topmost-first rendered candidates containing one canvas point coordinate." Confusable pairs: project_validate / arcavex_template_validate, project_preview / arcavex_render_preview. `_INSTRUCTIONS` (mcp_server.py:74-95) names 24 prefixed tools and none of these; the skill mentions only project_snapshot and layer_tree in passing; `mcp serve` takes no flag to hide them. No mis-call was observed by tracer or verifier.

**Impact.** Half the tool list a host like Claude Desktop shows the person is jargon, and a fresh assistant sees two validate-shaped and two preview-shaped tools with no guidance — clutter/friction, not an observed wrong turn.

**Fix.** Prefix the desktop tools (`arcavex_desktop_*`) or gate them behind `mcp serve --desktop`, and add one sentence to the instructions saying unprefixed tools are for the Desktop app. (`src/arcavex/clients/mcp_server.py `_TOOL_METHODS` (585-632) and `_INSTRUCTIONS` (74-95)`)

**Status: deferred.** renaming the 13 desktop tools needs the engine, the Rust gateway and the generated TypeScript contracts to move together; `97a62ad` explains them in the instructions instead

<sub>Sources: t3:T3-04</sub>

### BX-28 (P2, learn, ai-ux) — Server `instructions` is one 1,652-char paragraph that opens with a loop assuming an existing template and puts 'READ THE GUIDE FIRST: skill://…/SKILL.md' as its last sentence; `arcavex mcp tools` never prints the instructions the README says the server advertises

**Evidence.** mcp_server.py:74-95 `_INSTRUCTIONS` begins "Arcavex rendering engine, MCP authoring surface. ... Typical loop: arcavex_template_inspect to read the contract and its node ids, arcavex_template_patch ..." and ends "Starting from nothing: arcavex_template_new ... READ THE GUIDE FIRST: the resource skill://arcavex-design-studio/SKILL.md ..." (verifier measured 1652 chars, no line breaks). `arcavex mcp tools` (174 lines) and `--json` contain no 'READ THE GUIDE'/'instruction'; README.md:338 says the numbered loop is 'also the server's advertised instructions' and that loop also starts at template_inspect. Mitigation: resources/list returns SKILL.md first and README.md:333-336 describes the resources.

**Impact.** A non-technical person has no template, so the first suggested action has nothing to act on; the right first move (read SKILL.md, then template_new) is the last sentence of a wall of text; a person checking with `mcp tools` never sees the instructions.

**Fix.** Reorder the instructions (1 read SKILL.md, 2 no template → template_new, 3 have one → inspect→patch→validate→preview→render, 4 vocabulary, 5 editor) with line breaks and print them at the top of `arcavex mcp tools`. (`src/arcavex/clients/mcp_server.py:74 (_INSTRUCTIONS) and the `mcp tools` command`)

**Status: fixed.** `97a62ad` — instructions reordered: guide, start from nothing, the loop, vocabulary

<sub>Sources: t3:T3-05</sub>

### BX-29 (P2, learn, ai-ux) — Missing MCP arguments surface as raw pydantic text (no ARC code/hint) unlike every domain error, no tool has per-parameter descriptions, and the skill's 'submit an empty transaction and the engine states the shape back' shortcut only works once the outer envelope is already right

**Evidence.** Calling any of arcavex_template_new/editor_apply/template_patch/render_preview/project_create/render/layout_inspect with `{}` -> isError:true "Error executing tool arcavex_template_new: 1 validation error for template_newArguments\ntarget\n  Field required [type=missing, ...] For further information visit https://errors.pydantic.dev/2.13/v/missing" — versus a domain error's `{"ok": false, "diagnostics": [{"code": "ARC-LIB-001", ..., "hint": ...}]}`. Refuted portion: argument names ARE discoverable — every tool publishes inputSchema with properties and `required` (41 with properties, 25 with required; template_patch carries a full PatchOp $defs block), which real hosts show the model; the tracer's 7 blind `{}` calls were a harness artifact (its proxy printed 140 chars of description and no schema). Confirmed: 0 of 46 tools carry per-property descriptions (no Field()/Annotated in mcp_server.py), so 'template' = path vs library ref is not in the schema. Unverified related: `arcavex_editor_apply '{}'` -> pydantic 'transaction Field required' while engine-and-loop.md:106-107 promises the engine states the whole shape back — only `{transaction:{command_id, project_path, base_project_revision, actor, commands: []}}` yields ARC-EDT-010 with the shape (T5-10); insert_after needed a 'node' key, first guess 'value' refused with the same generic hint (T5-09, partially answered by the schema's $defs).

**Impact.** When a missing-argument error does occur it names the field, so recovery is one retry; the inconsistency and the absent parameter semantics are friction, not a retry loop, in a real host.

**Fix.** Wrap argument-validation errors into the coded diagnostic envelope, add per-parameter descriptions (Annotated/Field) to every tool, and give the minimal editor envelope in the skill. (`src/arcavex/clients/mcp_server.py (tool signatures/docstrings ~125-137; FastMCP registration at :643 to wrap validation errors); references/engine-and-loop.md:106-107`)

**Status: fixed.** `af8ab60` — a missing or mistyped argument returns the same coded envelope as every other refusal, listing the tool's required and optional fields; all 47 tools now describe every parameter

<sub>Sources: t5:T5-03, t5:T5-09 (unverified), t5:T5-10 (unverified)</sub>

### BX-30 (P2, learn, docs) — The skill and two source docstrings falsely claim `style.align` is 'stored and never applied'; the compiler honours it (falls back to style.align when paragraph.align is absent), so the `template new` scaffold that uses it is correct and the guide is wrong

**Evidence.** engine-and-loop.md:119-120 "Alignment is `paragraph.align`, not `style.align`. The schema accepts both; the text renderer reads only `paragraph`, so a value written to `style.align` is stored and never applied." (repeated at kernel/api.py:1401-1402 and services/authoring.py:101-102). Scaffold title/subtitle/badge nodes: `style: {..., align: start}` (authoring.py:165,174,187). Verifier rendered three variants: `style.align: end` vs `paragraph: {align: end}` produce byte-identical PNGs (22,759 bytes), both differing from `start` in the title row bbox (68,496,949,562). compiler.py:2582 `align = p.get("align", style.align)`; :3066 validates style.align (ARC-TPL-037). Residual truth: if both are set, paragraph.align wins. Two tracers (T4-05, T5-11) reported the contradiction with the tracer-side framing that the scaffold teaches a trap — that framing is refuted.

**Impact.** An assistant reading the skill may needlessly rewrite the scaffold or wrongly tell the user the scaffold's alignment does nothing; the render is right either way.

**Fix.** Correct the 'two traps' text (and the two docstrings) to say paragraph.align overrides style.align when both are set, matching compiler.py:2582. (`skills/arcavex-design-studio/references/engine-and-loop.md:119-120; src/arcavex/kernel/api.py:1401-1402; src/arcavex/services/authoring.py:101-102`)

**Status: fixed.** `67079d1` — paragraph.align is primary and style.align an honoured fallback, verified by byte-identical renders

<sub>Sources: t4:T4-05, t5:T5-11 (unverified, framing refuted)</sub>

### BX-31 (P2, learn, docs) — `arcavex_font_list` marks bundled fonts `installed: false` and reports paths inside the developer checkout, reading as 'unusable' to an assistant

**Evidence.** unverified. `{"family": "Lalezar", "bundled": true, "installed": false, "files": [{"path": "C:\\...\\arcavex-wt\\desktop-phase2\\library-seed\\fonts\\Lalezar-Regular.ttf", "installed": false}]}`; it took a render to confirm Lalezar works. Only 4 families ship (Estedad, Inter, Lalezar, Vazirmatn) and `font add` is shell-only, so a 'retro' brief had one display option over MCP. (t2 observed the uv-tool install's `font list --json` correctly pointing at the wheel's _bundled/fonts, so the checkout path is a dev-venv artifact.)

**Impact.** The assistant may avoid a perfectly usable bundled face or waste a render confirming it.

**Fix.** Report `available: true` for bundled families (reserve `installed` for ARCAVEX_HOME/fonts) and consider bundling one more Latin display/serif face. (`font_list output model (src/arcavex/services/fonts or kernel/api.py font_list)`)

**Status: fixed.** `206b307` — every resolvable family reports `available`, with `source` naming bundled or installed

<sub>Sources: t5:T5-17 (unverified)</sub>

### BX-32 (P2, design, user-ux) — `line_height` is rejected (ARC-TPL-053) and the bundled display face Lalezar has a ~1.57x line box (vs Inter ~1.22x) documented nowhere, so a wrapped headline reads as loosely leaded and must be split into two anchored nodes

**Evidence.** layout inspect: two lines of 46pt Lalezar -> text bounds height 144pt (72pt/line, 1.57x); Inter 46pt -> 112pt (1.22x); one-line Lalezar 46pt -> 72pt; 150pt Lalezar -> 209pt (1.39x). `line_height: 1.1` -> "ERROR ARC-TPL-053 Node 'kicker' sets 'line_height', which is not supported in this build ... hint: Line-height control arrives when the text stack gains strut support." (compiler.py:3033). Honestly documented in template-schema.md:265 and known-limitations.md:36-37; per-font line-box ratios appear in no doc or skill. Tracer's workaround: split the statement into kicker_a/kicker_b and anchor the second at `kicker-a.bottom - 22pt`. Unverified T5-18 adds: valid paragraph fields are only align, direction; fit has no max_lines; Lalezar's 132px box shows ~50px of empty padding each side so box-based overlaps flag halos that are not ink.

**Impact.** Vertical rhythm has to be tuned by eye over several preview rounds and the template becomes less reusable (one variable split into two) — friction at the design stage; the result is not wrong.

**Fix.** Implement `line_height`/`leading` (and `fit.max_lines`) on text nodes; until then document the bundled faces' line-box ratios so the two-node workaround is predictable. (`product: honour `line_height` (src/arcavex/services/template/compiler.py:3033); interim docs/known-limitations.md:36`)

**Status: deferred.** `line_height` needs strut support in the text stack (known limitation ARC-TPL-053); the skill now states the bundled faces' line-box ratios

<sub>Sources: t4:T4-06, t5:T5-18 (unverified)</sub>

### BX-33 (P2, design, docs) — ARC-PRJ-001 hints are CLI-flavoured when returned over MCP ('pass --project <dir>, or create one with arcavex project new') though the MCP field is `project` and the tool is `arcavex_project_create`

**Evidence.** `project_snapshot {}` and `layer_tree {}` over MCP -> "No project found (no project.yaml in this or any parent directory)" hint "Run inside a project, pass --project <dir>, or create one with 'arcavex project new'."; with a bad dir -> "No project.yaml under --project ...". Source: services/projects.py:126-144 (catalog copy diagnostics_catalog.py:1141-1147); MCP params `project: str | None` (mcp_server.py:197, 224-229); arcavex_project_status's description also says '(or --project)'. The correct field name is in the tool schema, so friction not a wrong turn.

**Impact.** Over MCP there is no 'inside', the flag does not exist, and the named command is a CLI one; the assistant may try `--project` or a CLI command first.

**Fix.** Choose the hint by transport: over MCP say "pass 'project': <absolute dir>, or create one with arcavex_project_create". (`src/arcavex/services/projects.py:126-144 (keep diagnostics_catalog.py:1141-1147 in sync)`)

**Status: fixed.** `edf34cc` — ARC-PRJ-001, ARC-TPL-021/091/100/102 and the compiler's locale and style hints name the MCP argument beside the CLI flag

<sub>Sources: t5:T5-08</sub>

### BX-34 (P2, design, ai-ux) — No command, tool or template produces a comparison board/contact sheet, yet SKILL.md Step 9 says 'Show the strongest board or reference sheet' and the README's ratio boards are hand-made JPGs

**Evidence.** grep board|sheet|contact|compare over `arcavex --help` and every subcommand's --help, the 46 MCP tools, docs/cli.md, src/, scripts/ -> nothing (only 'contact.email' keypath examples). render/preview take one --format/--locale and one -o. README.md:132 embeds examples/future-archive-poster/output/en-ratio-board-readme.jpg (added in commit 6307408, no generator in tree); graphic-style-lab's reference-sheet.yaml is a hand-authored 1920x1200 template with ~19 example-specific variables. SKILL.md:163 is the only 'board' in the skill; references/*.md have no board/montage guidance.

**Impact.** Comparing four ratios or two locales means four or eight separate files/windows for the person, or the assistant hand-authoring a composite template.

**Fix.** Add a labelled grid/board command (or ship a generic contact-sheet template) and reference it from Step 9. (`product: `arcavex board TEMPLATE --formats a,b --locales x,y -o board.png` (or a documented generic contact-sheet template); skills/arcavex-design-studio/SKILL.md:163`)

**Status: deferred.** a board/contact-sheet command is a feature, not a repair; backlog

<sub>Sources: t6:T6-08</sub>

### BX-35 (P2, see-result, ai-ux) — No document or skill step tells the assistant how the person gets to see the result — hand over the absolute path, open the PNG (`Invoke-Item`/`start`/`open`), attach it, or point to the desktop app; every instruction is about the assistant looking at pixels itself

**Evidence.** SKILL.md:130 "preview and look at the pixels"; :132-133 "Run it; do not imagine its output"; :136 "Show work early"; :163-164 (Step 9 — Deliver) "Show the strongest board or reference sheet inline. Provide renders, the editable template, data, ..." — no host caveat; engine-and-loop.md:45-46 "`arcavex_render_preview` returns the image itself, so you can look at it. On the CLI, render to a file and read that file."; verification.md:21 "Look at the pixels — full resolution". grep Invoke-Item|xdg-open|start x.png|open x.png|image viewer|output path|attach|open the|for the person over README.md, docs, skills, examples/*/README.md -> only docs/agent-runs/phase-01-dx-design-review.md:182 (internal) and engine-and-loop.md:79 (a tool input). Every quick-start step ends at the engine's "Rendered X.png" line. README.md:327 confirms render_preview returns image content — works only where the host renders images (verifier could not observe a successful preview payload; from the tool description). The one tracer who opened both PNGs for the person did so on its own initiative.

**Impact.** In terminal hosts (Claude Code, Codex CLI) an image the assistant Reads is not shown to the person; a non-technical user is left with a filename in terminal scrollback and no instruction to open it.

**Fix.** Add a deliver step: state the absolute output path and open it for the person (`Invoke-Item` on Windows / `open` / `xdg-open`) or attach it via the host's file mechanism, noting 'inline' only works where the host displays images. (`skills/arcavex-design-studio/SKILL.md Step 9 (line 163) with a matching sentence at references/engine-and-loop.md:45-46; docs/quick-start.md after the first render`)

**Status: fixed.** `8db4fae` — Step 9 opens the file for the person and states its path; `f640a53` — the README says the same

<sub>Sources: t6:T6-01, t7:T7-07, t1:T2-15 (unverified)</sub>

### BX-36 (P2, see-result, ai-ux) — `arcavex render` (human, --json, and MCP `arcavex_render`) reports a CWD-relative `output_path`, while `preview` reports an absolute one; over MCP the file lands in the server process's working directory

**Evidence.** From a subdirectory: `render ... --json` -> "output_path": "announcement-poster.portrait.png", "inferred": {"output": "announcement-poster.portrait.png"}; human "inferred: output=announcement-poster.portrait.png / Rendered announcement-poster.portrait.png"; with `-o out/rel.png` -> "out\\rel.png". `preview --json` -> "output_path": "C:\\...\\home\\cache\\preview\\744fd17e0571a789.portrait.png" (absolute). MCP `arcavex_render` with no `output` -> same relative name, file written into the MCP client's CWD (the server's working directory). Source: kernel/api.py:2185 `inferred["output"] = str(default)`, :2259 `str(output)` with no resolve(); cli.py:330 `Rendered {result.output_path}`. docs/quick-start.md:27-30 shows the relative form; the skill's map uses `-o out.png`.

**Impact.** An assistant that ran from another directory, or a person reading the transcript, must reconstruct where the file landed; over MCP the location was never chosen by the person and is not visible in the response. Files are written correctly.

**Fix.** Resolve `output_path` (and inferred.output) to an absolute path in the render result so CLI, --json and MCP all report where the file actually is. (`src/arcavex/kernel/api.py (render_file path stringification ~lines 2185, 2259) so CLI --json, cli.py:330 and MCP inherit it`)

**Status: fixed.** `c9812dc` — absolute `output_path` in JSON and MCP results; the human line stays as typed

<sub>Sources: t6:T6-07</sub>

### BX-37 (P2, see-result, user-ux) — `arcavex preview` and `arcavex render` print the output path Rich-soft-wrapped mid-filename in an 80-column terminal (also with --no-color)

**Evidence.** COLUMNS=80: "compile=51.5ms render=331.5ms -> " NEWLINE "C:\Users\payam\Downloads\arcavex-beginner\verify\T6-02\home\cache\preview\0fcfc" NEWLINE "e5186da68d9.portrait.png" (tracer: split at "dd885c21f53ac4d" / "0.portrait.png"); same with --no-color; intact at COLUMNS=120/200 and in --json. `render -o <long path>` at 80 cols: "Rendered " NEWLINE "C:\...\out\a-very-long-output-d" NEWLINE "irectory-name\announcement-poster-output.png". Source: cli.py:690-693 console.print(f"...-> {res.output_path}") and cli.py:330, Rich Console default soft-wrap; wrap point depends on ARCAVEX_HOME length.

**Impact.** A person (or an assistant parsing human output) copying the path gets two fragments; pasting into a viewer fails.

**Fix.** Print the path on its own line with soft-wrap disabled (`soft_wrap=True`/`overflow='ignore'` or plain print), ideally before the timings. (`src/arcavex/clients/cli.py:690-693 (preview) and :330 (render)`)

**Status: fixed.** `8f9b634` — the path first, whole, on its own line

<sub>Sources: t6:T6-02</sub>

### BX-38 (P2, see-result, ai-ux) — `project_preview` (the preview that uses real project data) returns only cache paths and null timings, while `arcavex_render_preview` returns the image — so the project-aware preview cannot be looked at inside a chat host

**Evidence.** unverified. project_preview -> previews[].output_path = "...\home\cache\preview\7800fe08cca92439.square.png", no image content (proxy reported no images_saved_to), compile_ms/render_ms null; arcavex_render_preview -> image content saved as preview-00N.png. Tool description (verified elsewhere): "project_preview — Render structured per-target project preview reports for desktop viewers."

**Impact.** The assistant must fall back to render_preview with a hand-supplied data path, which is exactly the path where scaffold placeholder data diverged from project data (BX-19).

**Fix.** Return image content blocks from project_preview (or a per-target `image: true` flag) and fill compile_ms/render_ms. (`src/arcavex/clients/mcp_server.py project_preview`)

**Status: fixed.** `21ec0d4` — `project_preview` returns one image per rendered target beside its structured report, with real timings

<sub>Sources: t5:T5-13 (unverified)</sub>

### BX-39 (P2, see-result, performance) — The skill says 'look at the pixels — full resolution, not a thumbnail' with no screen-DPI guidance, and render_preview has no max-size option, so a print-DPI template pushes the assistant to read a multi-megabyte PNG per iteration

**Evidence.** unverified. verification.md:21 "2. **Look at the pixels** — full resolution, not a thumbnail". Measured: `render --dpi 300` -> 3375x4219, 3,653,490 bytes, 4279 ms wall (base64 4,871,320 chars); authored 96 dpi -> 1080x1350, 597,415 bytes, 1741 ms (base64 796,556); preview --dpi 300 render=2448 ms vs default 497 ms. arcavex_render_preview inputSchema: template, data, format, locale, style, dpi, debug — no max_px/scale (consistent with verified BX-14 schema dump). grep -i 'screen|--dpi' docs/quick-start.md -> none; README.md:285-291 lists DPI precedence but does not frame 96 dpi as screen preview. The Read tool downscaled the 3375x4219 image to 1600x2000 anyway.

**Impact.** ~5x slower renders and ~6x larger MCP payloads per iteration on print templates, for pixels the assistant never sees.

**Fix.** Tell the assistant to iterate at 96 dpi and check full resolution once before delivery, and add a `max_px`/`scale` bound to render_preview. (`skills/arcavex-design-studio/references/verification.md:21 and engine-and-loop.md; src/arcavex/clients/mcp_server.py render_preview`)

**Status: fixed.** `21ec0d4` — `max_px` bounds a preview by its longest side and reports the dpi and pixel size it actually used; `8db4fae` — the skill says to iterate at 96 dpi

<sub>Sources: t6:T6-09 (unverified)</sub>

### BX-40 (P2, iterate, bug) — The preview stable path is keyed only on template path + format, so previews of different --data files or DPIs overwrite the same file; docs describe it only as 'a stable preview path ... so an external viewer can watch one file'

**Evidence.** Four preview --json runs (data A, data B, A at --dpi 300, A again) all returned the identical output_path `...\cache\preview\eba9691f50460961.portrait.png` with content_sha256 018162c0…, 3fedc42a…, 86ad57e8… (3375x4219, 3.65 MB), 018162c0… (1080x1350) — one file in the cache dir throughout. kernel/api.py:2846-2861 `preview_path(template, format_name)`: key = sha256(abs template path)[:16]; data/dpi/locale/style not inputs. Intentional per docs/agent-runs/phase-01-brief.md:45; docs/cli.md:114-115 does not say the slot is per template+format. CLI --json and MCP return the correct content per call, so only a human looking at the on-disk file (or a --watch session) is affected.

**Impact.** A person's open viewer shows whichever variant ran last with no indication which; with --watch running on one data file another preview flips the live view to other content.

**Fix.** Document that the preview slot is per template+format and that data/DPI/locale variants overwrite it — or include data path and dpi in the stable-path hash. (`docs/cli.md:113-115; alternatively src/arcavex/kernel/api.py:2859 (Facade.preview_path key)`)

**Status: fixed.** `be1d9a2` — data, locale, dpi and style enter the stable-path key; the plain template+format path is unchanged

<sub>Sources: t6:T6-03</sub>

### BX-41 (P2, iterate, docs) — `preview --watch` works (re-render 0.5-1.5 s after a save) but is absent from quick-start, tutorials, the skill and MCP, so the 'person watches while the assistant edits' experience is never offered

**Evidence.** watch.log: "watching for changes… (Ctrl+C to stop) / changed=(initial) compile=67.4ms render=401.0ms -> <path> / changed=...\watch-data.yaml compile=120.7ms render=328.4ms -> <same path>"; cache PNG mtime updated 0.5 s (tracer) / 1.4 s (verifier) after the edit and shows the new text. Documentation: README.md:203 (command table one-liner), docs/cli.md:36,107,113-115, plus known-limitations.md:134 and performance.md:55 as asides. grep -i watch docs/quick-start.md docs/tutorials/ skills/ -> only art-direction.md:18 'Watch for'. quick-start's seven steps are all `arcavex render`. MCP tools: grep watch|live -> 0; arcavex_render_preview is one-shot. `preview --watch` prints only the path, not how to open it; Windows Photos/most browsers do not auto-reload.

**Impact.** A non-technical person gets successive 'Rendered x.png' messages instead of a window that updates; the live loop is only reachable with CLI access, so an MCP-only assistant cannot offer it at all.

**Fix.** Add a 'Watch it change' step (start `preview --watch`, open the printed path in a live-reloading viewer, then edit) to quick-start and the skill. (`docs/quick-start.md (add a 'Watch it change' step); skills/arcavex-design-studio/SKILL.md Step 7`)

**Status: fixed.** `3f5819a` — quick start step 6 'Watch it change'; `67079d1` — the skill's live-view paragraph

<sub>Sources: t6:T6-04</sub>

### BX-42 (P2, iterate, ai-ux) — `layout inspect` reports every intentional containment as a `content` overlap (stroke-only frames, tall line boxes over neighbours) and a 0.13% width delta as `shrunk`, so real collisions land at the bottom of 10-13 noise lines

**Evidence.** On golden-crust (window): "overlaps: 12 content, 0 effect spill / plate-inner ∩ date-line ... / badge-top ∩ badge-bottom ... / name-a ∩ descriptor ... / kicker-a ∩ badge ..."; "name-a ... overflow: shrunk (measured 739.9x218.0pt in 740.9x218.0pt)" (1.0pt of 740.9). plate-inner is stroke-only (`fill: "#00000000"`, size 97%x90%) — below the ≥90%-both-axes backdrop exemption in kernel/api.py `_is_backdrop` (~3714-3730). Shrunk threshold: services/text/service.py:35 `_FIT_EPS = 0.25` font-size points, and the report shows only box-width delta. docs/cli.md:283 labels `content` "A genuine collision" while :273 concedes such overlaps are usually intentional. Refuted portion: a real root-level badge∩plate collision IS reported (verifier moved the badge: "overlaps: 13 content ... plate ∩ badge") — but 13th, after twelve intentional pairs; known-limitations.md:51-53 and SKILL.md:148-149 already warn about per-group scope.

**Impact.** An assistant filtering on `kind == content` chases noise and must read every line to find the one that matters; friction, not a wrong result.

**Fix.** Suppress overlaps where a transparent-fill/stroke-only sibling fully contains the other or the intersection is below a fraction of the smaller node, report shrink only above a tolerance (e.g. >2% or >1pt font), and soften cli.md:283's 'genuine collision'. (`src/arcavex/kernel/api.py `_is_backdrop` / `_collect_overlaps` (~3685-3730); docs/cli.md:283`)

**Status: fixed.** `6bb4f51` — a stroke-only frame, and a filled plate painted beneath what it contains, are structure rather than collisions; a graze under 1pt or 2% of the smaller box is a new `touch` kind; a text node's box narrows to its shaped width. On the bakery poster 11 and 12 collision lines per format became 6 and 6, with the real badge-on-plate collision still reported. `8839045` — a shrink is flagged only when the size moved, and shows both sizes. **Correction to this finding:** the "0.13% shrink" reported above was an artefact of the old output, which printed box extents rather than sizes. Those were real 11%, 27% and 5.5% shrinks and they stay flagged

<sub>Sources: t4:T4-07</sub>

### BX-43 (P2, iterate, docs) — The skill's editor section never names the tool that accepts the transaction (`arcavex_editor_apply`), refers to the others by unprefixed names the server rejects (`editor_undo`, `editor_history`, `template_patch`), has no editor row in the Command↔MCP map, and never mentions the detach prerequisite (ARC-EDT-008)

**Evidence.** engine-and-loop.md:77-83 transaction block attributed to no tool; :109 "`editor_undo` / `_redo` / `_history` work on a history stored beside the project"; :112 "Prefer this to `template_patch`"; :114 "`editor_history` reports `branched_by_external_edit`". grep 'editor_apply|editor apply|arcavex_editor' over the skill -> nothing. Real names: arcavex_editor_apply/undo/redo/history, arcavex_template_patch; CLI `arcavex editor apply|undo|redo|history`. Proxy: `call editor_history` -> "Unknown tool: editor_history"; `arcavex_editor_history` reaches the engine. (layer_tree/project_snapshot are correctly unprefixed.) Unverified T5-16: editor_apply on a project pinning an external template -> ARC-EDT-008 "template lives outside the project ... hint: Copy the template into the project first — 'arcavex template detach' (or the arcavex_template_detach tool)"; the guide's editor section and project_create's description never mention detaching — one wasted transaction, good hint.

**Impact.** The assistant must search the catalog (or burn one wrong call) to find which name accepts the documented JSON, and one more transaction to learn about detach; minor friction.

**Fix.** Write the full `arcavex_editor_*` names, add 'submit via arcavex_editor_apply (CLI: arcavex editor apply)' above the transaction block, add an editor row to the map, and mention detach-before-edit. (`skills/arcavex-design-studio/references/engine-and-loop.md:77-115 and the map at :30-42`)

**Status: fixed.** `67079d1` — full `arcavex_editor_*` names and the tool that takes the transaction

<sub>Sources: t7:T7-05, t5:T5-16 (unverified)</sub>

### BX-44 (P2, iterate, ai-ux) — The semantic editor has no add-layer/insert command, so authoring any new node forces `template_patch`, which permanently branches the undo history the skill tells the assistant to rely on

**Evidence.** unverified. ARC-EDT-010 hint lists kinds: delete, duplicate, group, reorder, reparent, resize, rotate, set_display_name, set_effects, set_property, set_text, set_visibility, splice_children, translate (no insert/add) — consistent with the verified mcp_server.py:252-262 kind list. After template_patch on the detached template: editor_history "branched_by_external_edit": true, "can_undo": false. engine-and-loop.md:112 "Prefer this to `template_patch` for anything you may want to undo."

**Impact.** Every design that needs a new node loses the undo/redo safety net the guide recommends.

**Fix.** Add an `add_layer`/insert command kind (id, node mapping, parent, index) or record template_patch on a project-owned template into the history chain. (`src/arcavex/services/editor (command kinds) / src/arcavex/kernel/editor.py`)

**Status: planned.** wave 3: an `add_layer` command kind so new nodes do not force a history-branching patch

<sub>Sources: t5:T5-14 (unverified)</sub>

### BX-45 (P2, iterate, performance) — ~1.1 s process startup dominates each CLI render/preview round trip; nothing steers the assistant to `--watch` or the MCP server for iteration

**Evidence.** unverified. `arcavex --version` wall 1112 ms; render default 1741 ms total while the engine reports compile≈55-90 ms + render≈310-500 ms; preview 1509 ms for compile=90.1ms render=496.8ms. --watch saves-to-file in ~0.5 s and MCP calls have median 46 ms latency (t5 stats), but the skill does not say to use either for iteration.

**Impact.** Each 'change and look' cycle through the CLI costs 1.5-2.5 s of which under half a second is engine work.

**Fix.** Note the startup cost in the skill and recommend `preview --watch`/MCP for iteration; consider lazy imports to cut cold start. (`skills/arcavex-design-studio/references/engine-and-loop.md; CLI import path`)

**Status: fixed.** `67079d1` — the skill states the ~1 s start-up and steers iteration to `--watch`/MCP; lazy imports deferred

<sub>Sources: t6:T6-10 (unverified)</sub>

### BX-46 (P2, deliver, ai-ux) — `arcavex_project_render {dpi}` applies one DPI to every format, so the recorded run holds a 3375px Instagram tile and the correct 1080px tile had to be made with a non-recorded render

**Evidence.** unverified. Run 2026-09-04T23-20-44Z_343d3b outputs: golden-crust-project.square.png 3375x3375 (16.8 MB) and .story.png 3375x6000 (34.2 MB) from `project_render {dpi:300}`; Instagram wants 1080x1080. Per-format dpi lives in the formats block, which MCP cannot edit (BX-03).

**Impact.** The 'recorded, reproducible' artefact is wrong for one of the two deliverables.

**Fix.** Accept a per-format dpi map in project_render (and project.yaml), or default each format to its declared canvas dpi unless overridden by name. (`src/arcavex/clients/mcp_server.py project_render / project.yaml schema`)

**Status: fixed.** `4c27551` — `arcavex_project_render` takes a per-format dpi table; a format the project does not declare is refused rather than ignored, and the run manifest records the table so a rerun reproduces. A pre-existing defect surfaced with it: a recorded output's width and height stored the canvas's declared pixel size, not the size rendered under a dpi override

<sub>Sources: t5:T5-19 (unverified)</sub>

## Found while fixing

Writing the style-key tables against the engine surfaced defects no tracer had reached, each
reproduced with pixel checks before being handed to the render-defects agent: a `path` node
renders nothing at all; `opacity` is ignored on text and on a group's children unless the node
carries an effect; a `%` on a style length leaks an internal error (ARC-INT-999) instead of a
located diagnostic; `italic: "no"` renders italic; `opacity: 1.5` validates. The MCP-only trial's
transcript added `fill: none` refused while `transparent` is accepted, and hints for
over-constrained axes and percent offsets that state the rule without the idiom — all in the
authoring agent's scope.

## Refuted by the verifiers

Tracer claims that did not survive an independent attempt to reproduce them:

- T5-15 (unverified): 4000-char truncation of layout_inspect/layer_tree/project_snapshot — the tracer itself could not attribute it to server vs proxy; the T5-03 verifier showed the proxy already truncates tool descriptions to 140 chars and the T4-07 verifier received complete layout inspect output via CLI, so this is most likely a harness artifact, not an engine defect.
- T5-11 (unverified) as framed: 'scaffold teaches the style.align trap' — refuted by the T4-05 verifier, who rendered style.align:end and paragraph.align:end to byte-identical PNGs; style.align IS applied, the skill/docstrings are what is wrong (folded into BX-30 with corrected wording).
- T7-04 sub-claim that editor_apply/undo/redo/history are omitted from the skill — refuted: engine-and-loop.md:71-115 documents the transaction shape, all command kinds, and undo/redo/history; they are missing only from the map table (remainder kept as BX-16).
- T5-03 sub-claim 'tool argument shapes are undiscoverable' — refuted: every tool publishes an inputSchema with properties and `required` (template_patch includes a full PatchOp $defs block); the 7 blind `{}` calls were caused by the tracer's proxy dropping schemas (remainder kept as BX-29, P2).
- T5-06 headline 'inset frames cannot be expressed' — refuted: a `layout: vstack` group with `padding: 40px` and a fill/fill child yields an exact 40px inset in both formats; kept as a discoverability/hint gap (BX-18).
- T4-07 sub-claim that a cross-group badge/plate collision is 'not reported at all' — refuted for this template's structure: moving the badge into the plate produced 'plate ∩ badge' as the 13th overlap line (noise ordering kept as BX-42).
- T5-04 sub-claim that render `dpi` is undocumented — refuted: `dpi` is declared in the inputSchema of arcavex_render and arcavex_project_render; it is only absent from the one-line descriptions and the skill (remainder kept as BX-14).
- T4-04 sub-claim that an MCP-only assistant must trial-and-error the style keys — refuted: the first ARC-TPL-051 error (CLI and MCP) lists all 13 valid style fields; the generator-params half stands (BX-17).
- T3-06 suggested fix `FastMCP("arcavex", version=...)` — invalid for mcp 1.29.0 (FastMCP.__init__ has no `version` kwarg); the finding itself stands as BX-26 with the corrected fix target.

## Status summary

| Status | Count |
|---|---|
| fixed | 41 |
| in progress | 1 |
| planned | 1 |
| deferred | 3 |

Two things are the maintainer's decision rather than a repair: cutting the first release (the
release workflows exist and have never fired, so PyPI and the Releases page are empty — BX-01), and
distributing the desktop installer (BX-06). Until then the documented route is a `uv tool install`
from the repository URL — which installs `main`, so this branch has to land before that route
gives a reader the MCP server (BX-02) and everything else here.

## Artefacts

- Tracer sandboxes and outputs: `C:\Users\payam\Downloads\arcavex-beginner\t1…t7\` (the two
  delivered poster sets are under `t4\Golden Crust posters\` and `t5\work\deliver\`).
- MCP transcript of the MCP-only trial: `t5\mcp-transcript.jsonl` (131 calls, 37% refused; the
  refusals are dominated by the tracer's own deliberate probes of the validator).
- Workflow transcript: `~/.claude/projects/…/subagents/workflows/wf_01467481-c06/`.

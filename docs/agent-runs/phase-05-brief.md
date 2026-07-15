# Phase 05 brief — MCP authoring surface (spec §11 Phase 5)

## Scope

1. **MCP server** (`arcavex mcp serve`, §6.2): local stdio transport via FastMCP (the `mcp`
   package, already a dependency). Tool inputs/outputs mirror the service API and use the SAME
   pydantic models — no parallel schemas. MCP is OPTIONAL; no engine capability exists only
   through MCP (verify: every tool delegates to an existing kernel.api Facade method).
2. **Default v1 tool set** (§6.2) — thin wrappers over the facade:
   - `arcavex_template_list` / `_inspect` / `_validate` / `_patch`
   - `arcavex_project_create` / `_list` / `_status` / `_clone`
   - `arcavex_data_set` / `_import`
   - `arcavex_asset_add` / `_annotate`
   - `arcavex_render_preview` (returns image CONTENT directly; with `debug=true` overlays node
     ids/bounds/baselines/anchors/overflow — reuse Phase 2 debug overlay)
   - `arcavex_layout_inspect` (geometry + anchor derivations)
   - `arcavex_render`
   - `arcavex_run_list` / `_diff` / `_rerun`
   - `arcavex_diagnostic_explain`
   Facade methods that don't exist yet for these (patch_template, set_data, import_data,
   add_asset, annotate_asset, scaffold-ish) — implement the missing ones in kernel.api +
   services (they're in the §3.7 surface). NO MCP tools for writing/enabling extensions
   (deferred beyond v1, §6.2).
3. **Image content return**: render_preview returns MCP image content (base64 PNG) so an agent
   sees the render. layout_inspect returns structured geometry. Both use versioned models.
4. **Structured everything**: MCP returns structured diagnostics (the same Diagnostic model),
   never scraped console text. An agent inspects → patches → validates → previews →
   inspect_layout → renders using only supported authoring contracts (no code path).
5. **patch_template** (§3.7, §4.1.4): apply a path-addressed patch (set/remove/insert_*) to a
   template file on disk (ruamel round-trip preserving comments), returning the updated
   template info or located diagnostics. This is the AI mutation contract — stable node IDs,
   unknown path → error. changed-on-disk detection before applying (§8.3).
6. **data_set / import_data** (§3.7): set_data(project, keypath, value) writes a single value
   into project data (located validation); import_data(project, yaml_text, locale) merges a
   data document. Both atomic, both return diagnostics.
7. **asset_add / annotate_asset** (§4.7, §3.7): ingest an asset into the project/workspace CAS
   returning an AssetRef; annotate_asset writes sidecar annotations (facing/focal_point/tags)
   consumed by template expressions. Render-time image analysis stays prohibited — annotation
   is ingest-time stored data.
8. **Scripted agent sessions** (§8.5 agent dogfood): tests/mcp_sessions/ — drive the server
   in-process (FastMCP client or direct tool-function calls) through the loop: inspect → patch
   → validate → preview → inspect_layout → render, asserting each step's structured output.
   The exit-criterion scenario: an agent creates and CORRECTS a poster using only supported
   template operations (seed a broken template, agent inspects diagnostics, patches, re-validates
   to green, renders). Include a test that MCP tool schemas match the facade models.
9. **CLI**: `arcavex mcp serve` starts the stdio server; `arcavex mcp tools --json` lists the
   tool catalog (names + schemas) for discovery. Keep exit codes/JSON conventions.

## Non-goals
Extension SDK (Phase 6), JPEG/WebP/PDF + hardening (Phase 7). No MCP extension-authoring
tools (spec defers). No network transport (stdio only). No new rendering capability.

## Carry-over
Any open P3s from phase-04 (check the code/dx reviews). Notably: none block Phase 5.

## Constraints
- MCP mirrors the service API — same pydantic models, no divergent schema. If a model isn't
  MCP-serializable, fix the model, don't fork it.
- Clients (mcp_server.py) parse+present only; all logic in services/facade.
- Determinism unaffected; no wall-clock in outputs.
- Kernel pure; mcp_server is a client (may import kernel.api only).
- All existing tests green; new codes documented.

## Acceptance commands
```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\arcavex.exe mcp tools --json      # lists the tool catalog
.venv\Scripts\python.exe -m pytest tests/mcp_sessions -q   # scripted agent sessions
```
Plus an in-process scripted session (documented in the test) proving inspect→patch→validate→
preview→inspect_layout→render with structured outputs, and the create-and-correct scenario.

## Exit criteria (spec Phase 5)
An agent creates and corrects a poster using ONLY supported template operations (no code
execution path); MCP tools mirror the service API with structured diagnostics, preview image
content, and layout inspection; every MCP capability also reachable via CLI/API.

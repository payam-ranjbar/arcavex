# Phase 05 code review — MCP authoring surface

**Reviewer:** adversarial code review (read-only)
**Commit:** `eb50d77` (diff base `5350d77`)
**Date:** 2026-07-14
**Verdict:** ACCEPT WITH MINOR FINDINGS (no P0/P1). Phase 5 meets its exit criteria; all findings are P2/P3 and none block acceptance.

---

## Summary

Phase 5 adds an optional stdio MCP authoring surface (`clients/mcp_server.py`), the `arcavex mcp
serve` / `arcavex mcp tools` CLI, five new facade methods (`patch_template`, `set_data`,
`import_data`, `add_asset`, `annotate_asset`) plus `list_templates`/`list_projects`, their
orchestrator implementations, versioned result models, two new diagnostic codes
(ARC-TPL-110/111), and a `tests/mcp_sessions/` dogfood suite. The implementing agent died before
self-reporting; everything below was re-verified by execution.

The design is sound: every tool is a thin wrapper delegating to exactly one facade method, tool
output schemas are byte-for-byte the facade models (asserted by a real parity test), diagnostics
travel as the structured `Diagnostic` model, and the exit-criterion scenario performs a genuine
poster correction through authoring tools only. Gates are green.

## Gates (verified by execution)

| Gate | Result |
|------|--------|
| `pytest tests` | **461 passed** in 103s |
| `ruff check src tests` | All checks passed |
| `mypy --strict src/arcavex/kernel` | Success, no issues (12 files) |
| `lint-imports` | 3 contracts kept, 0 broken |
| `arcavex mcp tools --json` | 19 tools, `response_version: 1` |
| `pytest tests/mcp_sessions` | pass (part of 461) |

## Verification performed

- **Mirror principle (§6.2 / invariant 18):** `mcp_server.py` contains no business/render/compile
  logic — every method body is one `self._facade.<method>(...)` call plus serialization. All 19
  tools map to facade methods; `test_every_tool_delegates_to_a_facade_method` asserts each exists
  on `Facade`. mcp_server imports only `mcp`, `arcavex.bootstrap`, and `arcavex.kernel.*` (no
  services/builtin).
- **Schema parity:** `test_output_schemas_match_facade_models` asserts
  `catalog[name]["outputSchema"] == model.model_json_schema()` for all 18 structured tools;
  `render_preview` correctly declares `outputSchema: None` (mixed image+text). Patch input reuses
  the shared `PatchOp` `$defs`. Bad inputs return structured diagnostics, never tracebacks:
  missing template → ARC-TPL-001; unknown patch path → ARC-TPL-092; bad import YAML → ARC-TPL-002;
  non-mapping import → ARC-TPL-012; bad keypath → ARC-TPL-111.
- **patch_template:** comment-preserving ruamel round-trip (verified scaffold comment survives);
  unknown path → located ARC-TPL-092; changed-on-disk (edited file mid-flight with a stale
  `base_sha256`) → ARC-TPL-110, refused before any write; stable node-id addressing.
- **Exit criterion (create-and-correct):** seeded broken poster (invalid fill) →
  validate reports ARC-IR-030 → explain → patch `nodes.background.style.fill` → revalidate green →
  render real PNG. Driven both through the tool callables and the live FastMCP `call_tool`.
- **render_preview:** returns `Image` content whose bytes decode as a valid PNG (magic + 19 KB);
  `debug=true` produces an overlay image; a compile failure returns no image plus a structured
  `PreviewResult` carrying coded diagnostics.
- **layout_inspect:** structured geometry (`canvas_px`, per-node `bounds_pt`), not console text.
- **data/assets:** `set_data`/`import_data` atomic writes + located validation; overlay merge
  semantics correct; `add_asset` CAS-ingests → `AssetInfo`; `annotate_asset` accumulates sidecar
  annotations (merge, not replace); render-time image analysis absent (annotation is stored data).
- **No extension-authoring tools** (spec defers): confirmed — 19 tools, none write/enable code.
- **Regression:** `arcavex render examples/hello-poster --format square` renders intact; kernel
  still pure; determinism unaffected by MCP.
- **New codes documented:** ARC-TPL-110/111 in catalog + `docs/diagnostics/`; covered by
  `test_every_emitted_code_is_documented` / `test_docs_diagnostics_mirror_catalog`.

---

## Findings

### CR-1 (P2) — Multi-verb `PatchOp` silently applies one verb and drops the rest
`PatchOp` permits all four verb fields simultaneously and `to_patch_dict()` returns the first it
finds (`set`, by iteration order), discarding the others with no error. A malformed op like
`PatchOp(set="nodes.title.style.color", value="#abcabc", remove="nodes.subtitle")` returns
`ok=True, applied=1` while the `remove` is silently ignored — an agent believes both mutations
landed. The AI mutation contract should reject ambiguous ops (0 or ≥2 verbs) with a located
ARC-TPL-092 at the model boundary rather than partially applying. (A no-verb op is already caught
downstream, but only because `{}` reaches the patcher.)
*Evidence:* `to_patch_dict` returns `{'set': ..., 'value': ...}`; tool call reports applied=1,
subtitle survives.
*File:* `src/arcavex/kernel/api.py` `PatchOp.to_patch_dict` (~L512).

### CR-2 (P2) — CLI/MCP asymmetry: five authoring operations have no CLI subcommand
`patch_template`, `set_data`, `import_data`, `add_asset`, and `annotate_asset` are exposed as MCP
tools (and Python facade methods) but have **no** CLI command (`cli.py` grows only `mcp
serve`/`tools`). This satisfies invariant 18 literally — no exclusive *engine* capability, since
all live on the shared facade/Python API — and the brief scoped these to the `§3.7` facade surface
only. But it is in tension with spec line 39 ("MCP exposes the same service operations as the CLI…
the CLI remains complete"): a CLI user cannot patch by node id, set/import data, or ingest/annotate
assets, while an MCP agent can. Recommend either adding the CLI subcommands or an explicit spec
note that these authoring ops are agent-surface-first. Not blocking (brief did not require CLI).

### CR-3 (P3) — Client import boundary is convention, not linted
No import-linter contract constrains `arcavex.clients` to import only `kernel.api`. The three
contracts cover kernel purity and that builtins/services don't reach up — none stops `mcp_server`
(or `cli`) from importing `services`/`builtin` internals. `mcp_server` currently complies, but the
brief's claim that "import-linter contract covers it" overstates: the parse-and-present boundary is
enforced by review only. Consider a `clients → kernel only` forbidden contract.

### CR-4 (P3) — README documents no MCP surface
`README.md` has zero MCP mentions (no `arcavex mcp serve`/`tools`, no tool names), though MCP is an
advertised first-class interface (spec line 6). Discovery/docs gap.

### CR-5 (P3) — `set_data`/`import_data` validation is compile-only (no layout)
`_validate_project_data` intentionally skips the layout pass (needs render registries the
orchestrator doesn't hold), so `DataReport(ok=True)` can be returned for data that would overflow
at render. Documented in code; noted for awareness — an agent relying on the DataReport alone won't
see layout regressions until a `render_preview`/`layout_inspect` call.

### CR-6 (P3) — `render_preview` structured block carries wall-clock durations
The `PreviewResult` JSON block includes `compile_ms`/`render_ms`, so the agent-facing output is not
byte-reproducible across runs. This faithfully mirrors the existing CLI model (correct under the
mirror principle) but is worth noting against the "no wall-clock in outputs" goal; these are
durations, not timestamps.

---

## Commands

```
.venv\Scripts\python.exe -m pytest tests -q                 # 461 passed
.venv\Scripts\python.exe -m ruff check src tests            # clean
.venv\Scripts\python.exe -m mypy --strict src/arcavex/kernel # clean
.venv\Scripts\lint-imports.exe                              # 3 kept
.venv\Scripts\arcavex.exe mcp tools --json                  # 19 tools
.venv\Scripts\arcavex.exe render examples/hello-poster --format square -o <out>  # regression OK
```

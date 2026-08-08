"""MCP ↔ facade schema parity (spec §12.18, §6.2).

MCP mirrors the service API and defines no schema of its own. These tests assert that every
structured tool's output schema is exactly the JSON schema of the facade result model it
returns — so a tool result can never drift from what the CLI/Python API return — and that the
patch tool's input reuses the shared :class:`PatchOp` model rather than a parallel copy.
"""

from __future__ import annotations

from arcavex.clients.mcp_server import (
    _TOOL_METHODS,
    build_mcp_server,
    tool_catalog,
)
from arcavex.kernel.api import (
    AssetReport,
    CheckResult,
    DataReport,
    DiagnosticHelp,
    DiffReport,
    EffectListReport,
    EngineHandshakeReport,
    FontListReport,
    LayoutReport,
    PatchOp,
    PatchTemplateResult,
    ProjectListReport,
    ProjectResult,
    ProjectStatusReport,
    RenderResult,
    RerunReport,
    RunListReport,
    RunReport,
    StyleInspectReport,
    StyleListReport,
    TemplateInspectReport,
    TemplateListReport,
)

# Each structured tool maps to the exact facade model it returns. render_preview is absent: it
# returns mixed image + text content (its structured payload is a PreviewResult inside a text
# block), so it has no single output schema.
_TOOL_OUTPUT_MODELS = {
    "engine_handshake": EngineHandshakeReport,
    "arcavex_template_list": TemplateListReport,
    "arcavex_template_inspect": TemplateInspectReport,
    "arcavex_template_validate": CheckResult,
    "arcavex_template_patch": PatchTemplateResult,
    "arcavex_project_create": ProjectResult,
    "arcavex_project_list": ProjectListReport,
    "arcavex_project_status": ProjectStatusReport,
    "arcavex_project_clone": ProjectResult,
    "arcavex_project_render": RunReport,
    "arcavex_render_record": RunReport,
    "arcavex_data_set": DataReport,
    "arcavex_data_import": DataReport,
    "arcavex_asset_add": AssetReport,
    "arcavex_asset_annotate": AssetReport,
    "arcavex_style_list": StyleListReport,
    "arcavex_style_inspect": StyleInspectReport,
    "arcavex_effects_list": EffectListReport,
    "arcavex_font_list": FontListReport,
    "arcavex_layout_inspect": LayoutReport,
    "arcavex_render": RenderResult,
    "arcavex_run_list": RunListReport,
    "arcavex_run_diff": DiffReport,
    "arcavex_run_rerun": RerunReport,
    "arcavex_diagnostic_explain": DiagnosticHelp,
}


def _catalog() -> dict[str, dict]:
    return {t["name"]: t for t in tool_catalog(build_mcp_server())}


def test_catalog_lists_every_declared_tool() -> None:
    """The built server exposes exactly the declared tool catalog (names)."""
    catalog = _catalog()
    assert set(catalog) == {name for name, _ in _TOOL_METHODS}
    assert len(catalog) == 26


def test_output_schemas_match_facade_models() -> None:
    """Every structured tool's outputSchema is its facade model's JSON schema, byte for byte."""
    catalog = _catalog()
    for name, model in _TOOL_OUTPUT_MODELS.items():
        assert catalog[name]["outputSchema"] == model.model_json_schema(), name


def test_render_preview_returns_mixed_content_not_a_schema() -> None:
    """render_preview yields image content, so it declares no single output schema."""
    assert _catalog()["arcavex_render_preview"]["outputSchema"] is None


def test_patch_tool_input_reuses_the_shared_patchop_model() -> None:
    """The patch tool's 'ops' input is the shared PatchOp model, not a parallel schema."""
    schema = _catalog()["arcavex_template_patch"]["inputSchema"]
    assert "PatchOp" in schema.get("$defs", {})
    patchop_fields = set(PatchOp.model_json_schema()["properties"])
    assert set(schema["$defs"]["PatchOp"]["properties"]) == patchop_fields


def test_every_tool_delegates_to_a_facade_method() -> None:
    """No MCP tool has exclusive capability: each wraps a method that lives on the Facade path.

    The tool method bodies call ``self._facade.<method>``; here we assert the facade actually
    exposes the delegated surface the session tests exercise, so MCP adds no private power.
    """
    from arcavex.kernel.api import Facade

    for facade_method in (
        "engine_handshake",
        "list_templates", "inspect_template", "validate_template", "patch_template",
        "create_project", "list_projects", "project_status", "clone_project",
        "render_project", "record_render",
        "set_data", "import_data", "add_asset", "annotate_asset",
        "list_styles", "inspect_style", "list_effects",
        "render_preview", "inspect_layout", "render_file", "list_runs",
        "diff_runs", "rerun", "explain_diagnostic",
    ):
        assert callable(getattr(Facade, facade_method)), facade_method


def test_server_constructs_with_instructions() -> None:
    """The server object builds and advertises usage instructions for a connecting agent."""
    server = build_mcp_server()
    assert server.name == "arcavex"
    assert server.instructions and "arcavex_template_inspect" in server.instructions

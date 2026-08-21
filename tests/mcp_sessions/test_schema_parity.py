"""MCP ↔ facade schema parity (spec §12.18, §6.2).

MCP mirrors the service API and defines no schema of its own. These tests assert that every
structured tool's output schema is exactly the JSON schema of the facade result model it
returns — so a tool result can never drift from what the CLI/Python API return — and that the
patch tool's input reuses the shared :class:`PatchOp` model rather than a parallel copy.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

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
    HitTestReport,
    LayerTreeReport,
    LayoutReport,
    PatchOp,
    PatchTemplateResult,
    PreviewProjectReport,
    ProjectListReport,
    ProjectPolicyReport,
    ProjectResult,
    ProjectSnapshotReport,
    ProjectStatusReport,
    ProjectUIMetadataReport,
    ProposalActionReport,
    ProposalListReport,
    RenderResult,
    RerunReport,
    RunListReport,
    RunReport,
    StyleInspectReport,
    StyleListReport,
    TemplateInspectReport,
    TemplateListReport,
)
from arcavex.kernel.editor import (
    COMMAND_KINDS,
    HistoryReport,
    SemanticTransaction,
    TransactionReport,
)

_EXPORTER_SPEC = importlib.util.spec_from_file_location(
    "export_desktop_schemas",
    Path(__file__).parents[2] / "scripts" / "export_desktop_schemas.py",
)
assert _EXPORTER_SPEC is not None and _EXPORTER_SPEC.loader is not None
_EXPORTER = importlib.util.module_from_spec(_EXPORTER_SPEC)
_EXPORTER_SPEC.loader.exec_module(_EXPORTER)

# Each structured tool maps to the exact facade model it returns. render_preview is absent: it
# returns mixed image + text content (its structured payload is a PreviewResult inside a text
# block), so it has no single output schema.
_TOOL_OUTPUT_MODELS = {
    "engine_handshake": EngineHandshakeReport,
    "project_snapshot": ProjectSnapshotReport,
    "project_ui_metadata": ProjectUIMetadataReport,
    "project_ui_metadata_set": ProjectUIMetadataReport,
    "project_policy": ProjectPolicyReport,
    "project_policy_set": ProjectPolicyReport,
    "project_proposal_list": ProposalListReport,
    "project_proposal_approve": ProposalActionReport,
    "project_proposal_reject": ProposalActionReport,
    "layer_tree": LayerTreeReport,
    "hit_test": HitTestReport,
    "project_validate": CheckResult,
    "project_preview": PreviewProjectReport,
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
    assert len(catalog) == len(_TOOL_METHODS) == 38


def test_output_schemas_match_facade_models() -> None:
    """Every structured tool's outputSchema is its facade model's JSON schema, byte for byte."""
    catalog = _catalog()
    for name, model in _TOOL_OUTPUT_MODELS.items():
        assert catalog[name]["outputSchema"] == model.model_json_schema(), name


def test_direct_preview_is_mixed_but_project_preview_is_a_structured_report() -> None:
    """Project preview is a desktop contract, unlike direct image-plus-text preview output."""
    catalog = _catalog()

    assert catalog["arcavex_render_preview"]["outputSchema"] is None
    assert catalog["project_preview"]["outputSchema"] == PreviewProjectReport.model_json_schema()


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
        "project_snapshot", "project_ui_metadata", "set_project_ui_metadata",
        "project_policy", "set_project_policy", "list_project_proposals",
        "approve_project_proposal", "reject_project_proposal", "layer_tree", "hit_test",
        "validate_project", "preview_project",
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


def test_desktop_schema_export_writes_every_mcp_desktop_contract(tmp_path: Path) -> None:
    """Omitting a desktop report from the exporter would let generated TypeScript drift."""
    written = _EXPORTER.export_schemas(tmp_path)

    expected = {
        "engine-handshake.schema.json": EngineHandshakeReport,
        "project-snapshot.schema.json": ProjectSnapshotReport,
        "project-ui-metadata.schema.json": ProjectUIMetadataReport,
        "project-policy.schema.json": ProjectPolicyReport,
        "project-proposal-list.schema.json": ProposalListReport,
        "project-proposal-action.schema.json": ProposalActionReport,
        "layer-tree.schema.json": LayerTreeReport,
        "hit-test.schema.json": HitTestReport,
        "project-validate.schema.json": CheckResult,
        "project-preview.schema.json": PreviewProjectReport,
        "editor-transaction.schema.json": SemanticTransaction,
        "editor-transaction-report.schema.json": TransactionReport,
        "editor-history.schema.json": HistoryReport,
    }

    assert written == set(expected)
    for filename, model in expected.items():
        assert (tmp_path / filename).read_text(encoding="utf-8") == (
            json.dumps(
                model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True
            )
            + "\n"
        )

    fixtures = _EXPORTER.export_contract_fixtures(tmp_path)
    assert set(fixtures) == set(expected)
    assert json.loads(
        (tmp_path / "desktop-contract-fixtures.json").read_text(encoding="utf-8")
    ) == fixtures
    for filename, model in expected.items():
        # A canonical absolute path cannot be spelled the same way on every platform, so the
        # checked-in fixture carries a placeholder that callers materialize before validating.
        materialized = _EXPORTER.materialize_fixture(fixtures[filename])
        assert _EXPORTER.tokenize_fixture(
            model.model_validate(materialized).model_dump(mode="json")
        ) == fixtures[filename]


def test_desktop_fixtures_populate_the_branches_runtime_guards_must_police() -> None:
    """Empty-collection fixtures would let generated guards pass without exercising a contract."""
    fixtures = _EXPORTER.contract_fixtures()

    for filename, fixture in fixtures.items():
        # A request contract has no diagnostics to carry; every report does, and an empty list
        # would let its guard pass without ever exercising the diagnostic branch.
        if filename == "editor-transaction.schema.json":
            continue
        assert fixture["diagnostics"], filename

    # The command union is the widest branch in the whole desktop surface, so the transaction
    # fixture must reach every member rather than one representative kind.
    transaction = fixtures["editor-transaction.schema.json"]
    assert {command["kind"] for command in transaction["commands"]} == set(COMMAND_KINDS)
    assert fixtures["editor-transaction-report.schema.json"]["inverse"]["commands"]
    assert fixtures["editor-history.schema.json"]["entries"]

    proposal = fixtures["project-proposal-action.schema.json"]["proposal"]
    assert re.fullmatch(r"[0-9a-f]{64}", proposal["base_project_revision"])
    assert re.fullmatch(r"[0-9a-fA-F-]{36}", proposal["command_id"])
    assert proposal["created_at"].endswith("Z")
    assert proposal["command_payload"] and proposal["actor"]["channel"] == "mcp"

    layers = fixtures["project-ui-metadata.schema.json"]["metadata"]["layers"]
    assert layers["title"]["color"] == "#3A7BD5"
    assert fixtures["project-preview.schema.json"]["previews"][0]["inferred"]
    assert fixtures["layer-tree.schema.json"]["root"]["children"][0]["effects"]
    assert fixtures["hit-test.schema.json"]["candidates"]

"""Desktop handshake parity through the real MCP tool surface."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from arcavex.clients.mcp_server import ArcavexTools, build_mcp_server, tool_catalog
from arcavex.kernel.api import (
    EngineHandshakeReport,
    LayerUIMetadata,
    ProjectPolicyReport,
    ProjectSnapshotReport,
    ProjectUIMetadata,
    ProjectUIMetadataReport,
    ProposalActionReport,
    ProposalActor,
    ProposalListReport,
)
from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import ProjectService
from arcavex.services.proposals import ProposalService

_COMMAND_ID = "00000000-0000-4000-8000-000000000001"


def _project(root: Path) -> Path:
    project = root / "campaign"
    (project / "template").mkdir(parents=True)
    (project / "template/template.yaml").write_text("version: 0.1.0\n", encoding="utf-8")
    (project / "project.yaml").write_text(
        "name: launch\ntemplate: ./template\nformats: [square]\nlocales: []\n",
        encoding="utf-8",
    )
    return project


def test_engine_handshake_tool_returns_the_frozen_facade_model(tools: ArcavexTools) -> None:
    """The MCP wrapper must return the facade model itself, not a parallel payload."""
    report = tools.engine_handshake()

    assert isinstance(report, EngineHandshakeReport)
    assert report.response_version == 1
    assert report.mcp_contract_version == "2025-06-18"
    assert report.capabilities == sorted(report.capabilities)


def test_engine_handshake_tool_exports_the_shared_output_schema() -> None:
    """MCP schema drift from the Pydantic startup contract must fail at the catalog boundary."""
    catalog = {tool["name"]: tool for tool in tool_catalog(build_mcp_server())}

    assert "engine_handshake" in catalog
    assert catalog["engine_handshake"]["outputSchema"] == EngineHandshakeReport.model_json_schema()


def test_engine_handshake_dispatches_through_the_live_mcp_server(server) -> None:
    """The exact public tool name must return structured startup data over FastMCP dispatch."""
    _content, structured = asyncio.run(server.call_tool("engine_handshake", {}))

    assert structured["response_version"] == 1
    assert structured["mcp_contract_version"] == "2025-06-18"
    assert structured["doctor"]["checks"]


def test_project_snapshot_tool_returns_the_shared_facade_model(
    tools: ArcavexTools, tmp_path: Path
) -> None:
    """MCP must return the frozen snapshot model rather than a transport-owned payload."""
    report = tools.project_snapshot(str(_project(tmp_path)))

    assert isinstance(report, ProjectSnapshotReport)
    assert report.ok
    assert report.default_target is not None
    assert report.default_target.format == "square"


def test_project_snapshot_tool_exports_the_shared_output_schema() -> None:
    """MCP snapshot schema must be generated from the same Pydantic model as the facade."""
    catalog = {tool["name"]: tool for tool in tool_catalog(build_mcp_server())}

    assert "project_snapshot" in catalog
    assert catalog["project_snapshot"]["outputSchema"] == (
        ProjectSnapshotReport.model_json_schema()
    )


def test_project_snapshot_dispatches_through_the_live_mcp_server(
    server, tmp_path: Path
) -> None:
    """The public MCP tool must resolve a path and return structured revision data."""
    project = _project(tmp_path)

    _content, structured = asyncio.run(
        server.call_tool("project_snapshot", {"project": str(project)})
    )

    assert structured["response_version"] == 1
    assert structured["canonical_path"] == str(project.resolve())
    assert structured["project_revision"]
    assert structured["render_revision"]


def test_metadata_policy_and_proposal_tools_return_shared_facade_models(
    tools: ArcavexTools, tmp_path: Path
) -> None:
    """Desktop MCP wrappers must return kernel models, never transport-owned lookalikes."""
    project = _project(tmp_path)
    metadata = ProjectUIMetadata(
        layers={"title": LayerUIMetadata(display_name="Hero", locked=True)}
    )

    metadata_report = tools.project_ui_metadata_set(metadata, str(project))
    policy_report = tools.project_policy_set("review", "disabled", str(project))
    proposal_report = tools.project_proposal_list(str(project))

    assert isinstance(metadata_report, ProjectUIMetadataReport)
    assert metadata_report.metadata == metadata
    assert isinstance(tools.project_ui_metadata(str(project)), ProjectUIMetadataReport)
    assert isinstance(policy_report, ProjectPolicyReport)
    assert policy_report.policy.mode == "review"
    assert policy_report.policy.extensions == "disabled"
    assert isinstance(tools.project_policy(str(project)), ProjectPolicyReport)
    assert isinstance(proposal_report, ProposalListReport)
    assert proposal_report.proposals == []


def test_proposal_approve_and_reject_tools_return_shared_action_report(
    tools: ArcavexTools, tmp_path: Path
) -> None:
    """Approve/reject must preserve the authorization-state contract through MCP."""
    project = _project(tmp_path)
    projects = ProjectService()
    snapshots = ProjectSnapshotService(projects)
    proposals = ProposalService(projects, snapshots)
    revision = snapshots.snapshot(project=project).project_revision
    assert revision is not None
    proposals.enqueue(
        project=project,
        command_id=_COMMAND_ID,
        base_project_revision=revision,
        actor=ProposalActor(id="agent-7"),
        command_payload={"kind": "set_display_name"},
        created_at=datetime(2026, 8, 8, 12, 30, tzinfo=UTC),
    )

    approved = tools.project_proposal_approve(_COMMAND_ID, str(project))
    rejected = tools.project_proposal_reject(
        "00000000-0000-4000-8000-000000000002", "duplicate", str(project)
    )

    assert isinstance(approved, ProposalActionReport)
    assert approved.proposal is not None and approved.proposal.state == "authorized"
    assert isinstance(rejected, ProposalActionReport)
    assert not rejected.ok


def test_new_desktop_tools_export_shared_output_schemas() -> None:
    """MCP schema generation must stay pinned to the frozen kernel report models."""
    catalog = {tool["name"]: tool for tool in tool_catalog(build_mcp_server())}
    expected = {
        "project_ui_metadata": ProjectUIMetadataReport,
        "project_ui_metadata_set": ProjectUIMetadataReport,
        "project_policy": ProjectPolicyReport,
        "project_policy_set": ProjectPolicyReport,
        "project_proposal_list": ProposalListReport,
        "project_proposal_approve": ProposalActionReport,
        "project_proposal_reject": ProposalActionReport,
    }

    assert {
        name: catalog[name]["outputSchema"] for name in expected
    } == {name: model.model_json_schema() for name, model in expected.items()}


def test_new_desktop_contracts_dispatch_through_live_mcp_server(
    server, tmp_path: Path
) -> None:
    """The public transport names must parse inputs and return structured reports."""
    project = _project(tmp_path)

    _content, metadata = asyncio.run(
        server.call_tool("project_ui_metadata", {"project": str(project)})
    )
    _content, policy = asyncio.run(
        server.call_tool(
            "project_policy_set",
            {"project": str(project), "mode": "review", "extensions": "disabled"},
        )
    )
    _content, proposals = asyncio.run(
        server.call_tool("project_proposal_list", {"project": str(project)})
    )

    assert metadata["metadata"] == {
        "version": 1,
        "layers": {},
        "workspace": {
            "active_format": None,
            "active_locale": None,
            "layer_tree_mode": "definition",
            "selected_layer_ids": [],
        },
    }
    assert policy["policy"]["mode"] == "review"
    assert policy["policy"]["extensions"] == "disabled"
    assert proposals["proposals"] == []

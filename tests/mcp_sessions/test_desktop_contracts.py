"""Desktop handshake parity through the real MCP tool surface."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arcavex.clients.mcp_server import ArcavexTools, build_mcp_server, tool_catalog
from arcavex.kernel.api import EngineHandshakeReport, ProjectSnapshotReport


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

"""Desktop handshake parity through the real MCP tool surface."""

from __future__ import annotations

import asyncio

from arcavex.clients.mcp_server import ArcavexTools, build_mcp_server, tool_catalog
from arcavex.kernel.api import EngineHandshakeReport


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

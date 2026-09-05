"""Viewer-session MCP coverage for project validation and structured preview reports."""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp.types import CallToolResult

from arcavex.clients.mcp_server import ArcavexTools
from arcavex.kernel.api import CheckResult, PreviewProjectReport


def _project(root: Path) -> Path:
    project = root / "viewer-project"
    (project / "template").mkdir(parents=True)
    (project / "template" / "template.yaml").write_text(
        """version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 72}}
root:
  id: root
  type: group
  children:
    - id: card
      type: shape
      shape: rect
      style: {fill: "#123456"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
""",
        encoding="utf-8",
    )
    (project / "project.yaml").write_text(
        "name: viewer\ntemplate: ./template\nformats: [square]\nlocales: []\n",
        encoding="utf-8",
    )
    return project


def test_project_validate_returns_the_shared_check_result(
    tools: ArcavexTools, tmp_path: Path
) -> None:
    """Removing Facade project validation from MCP would leave viewer preflight unavailable."""
    report = tools.project_validate(str(_project(tmp_path)), formats=["square"])

    assert isinstance(report, CheckResult)
    assert report.ok
    assert report.diagnostics == []


def test_project_preview_returns_a_serializable_structured_report(
    server, tmp_path: Path
) -> None:
    """Losing the structured report from project preview would break the viewer contract.

    The tool now also returns the rendered images as content blocks (for an assistant that
    cannot open a path), so it answers with a ``CallToolResult``; the viewer reads
    ``structuredContent``, which must stay the exact report.
    """
    project = _project(tmp_path)

    result = asyncio.run(
        server.call_tool(
            "project_preview", {"project": str(project), "formats": ["square"], "dpi": 72}
        )
    )

    assert isinstance(result, CallToolResult) and result.isError is False
    structured = result.structuredContent
    report = PreviewProjectReport.model_validate(structured)
    assert report.ok
    assert len(report.previews) == 1
    assert report.previews[0].output_path is not None
    assert report.model_dump(mode="json") == structured

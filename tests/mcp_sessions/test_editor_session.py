"""Editor parity over MCP: the tool surface an AI client edits through.

The desktop and an AI client must get identical behavior from identical calls, so these tests
drive the same `ArcavexTools` methods FastMCP registers, over a real project, and assert the
reports — not just that the calls succeed.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from arcavex.bootstrap import build_facade
from arcavex.clients.mcp_server import _TOOL_METHODS, ArcavexTools

_TEMPLATE = """\
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
preview_data: {}
root:
  type: group
  id: root
  children:
    - id: title
      type: text
      text: "Session headline"
      style: {font: Inter, font_size: 24pt, color: "#222222"}
      constraints:
        anchor: {top: parent.top+20px, left: parent.left+20px}
        size: {w: 80%, h: fit_content}
"""


@pytest.fixture(scope="module")
def tools() -> ArcavexTools:
    return ArcavexTools(build_facade())


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "session-project"
    (root / "data").mkdir(parents=True)
    (root / "template.yaml").write_text(_TEMPLATE, encoding="utf-8")
    (root / "project.yaml").write_text(
        "name: session-project\ntemplate: template.yaml\nlocales: []\n"
        "formats:\n  - square\ndata: data/data.yaml\n",
        encoding="utf-8",
    )
    (root / "data" / "data.yaml").write_text("{}\n", encoding="utf-8")
    return root


def _transaction(tools: ArcavexTools, project: Path, text: str) -> dict[str, Any]:
    snapshot = tools.project_snapshot(str(project))
    assert snapshot.project_revision is not None
    return {
        "command_id": str(uuid.uuid4()),
        "project_path": str(project.resolve()),
        "base_project_revision": snapshot.project_revision,
        "actor": {"id": "mcp-session", "channel": "mcp"},
        "target": {"format": "square"},
        "commands": [{"kind": "set_text", "layer_id": "title", "text": text}],
    }


def test_every_editor_tool_is_registered() -> None:
    names = {name for name, _ in _TOOL_METHODS}
    assert {
        "arcavex_editor_apply",
        "arcavex_editor_apply_authorized",
        "arcavex_editor_undo",
        "arcavex_editor_redo",
        "arcavex_editor_history",
    } <= names


def test_apply_undo_redo_flow_through_the_mcp_surface(
    tools: ArcavexTools, project: Path
) -> None:
    applied = tools.editor_apply(_transaction(tools, project, "Edited over MCP"))
    assert applied.ok, applied.diagnostics
    assert "Edited over MCP" in (project / "template.yaml").read_text(encoding="utf-8")

    history = tools.editor_history(str(project))
    assert history.ok and history.can_undo

    undone = tools.editor_undo(str(project))
    assert undone.ok, undone.diagnostics
    assert "Session headline" in (project / "template.yaml").read_text(encoding="utf-8")

    redone = tools.editor_redo(str(project))
    assert redone.ok, redone.diagnostics
    assert "Edited over MCP" in (project / "template.yaml").read_text(encoding="utf-8")


def test_a_conflict_report_crosses_the_boundary_intact(
    tools: ArcavexTools, project: Path
) -> None:
    stale = _transaction(tools, project, "First")
    applied = tools.editor_apply(_transaction(tools, project, "Winner"))
    assert applied.ok

    refused = tools.editor_apply(stale)

    assert not refused.ok
    assert refused.conflict is not None
    assert refused.conflict.actual_project_revision == applied.project_revision


def test_an_invalid_transaction_is_a_diagnostic_not_an_exception(
    tools: ArcavexTools, project: Path
) -> None:
    report = tools.editor_apply({"commands": "not-a-list"})

    assert not report.ok
    assert any(d.code == "ARC-EDT-010" for d in report.diagnostics)

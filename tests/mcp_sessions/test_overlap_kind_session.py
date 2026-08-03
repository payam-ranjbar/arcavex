"""An agent filtering overlaps by ``kind`` over the MCP surface (P2-1).

``layout inspect`` is the primary geometry signal for an agent that cannot see the render. It
used to report a drop-shadow halo and a real 4pt text collision in identical shape, so the real
one could only be found by eye. These tests pin that the classification survives the MCP
boundary — through the tool callable and through the real ``call_tool`` dispatch — so an agent
can filter structurally instead of guessing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from arcavex.clients.mcp_server import ArcavexTools

# 400x400px at 72dpi, so 1px == 1pt. `strip` casts a 20pt blur (60pt reach) across a 10pt gap
# to `tag`; `venue-2` genuinely bites 4pt into `venue-1`.
_TEMPLATE = """\
version: 0.1.0

formats:
  sq: {canvas: {width: 400px, height: 400px, dpi: 72}}

root:
  type: group
  id: root
  children:
    - id: strip
      type: shape
      shape: rect
      style: {fill: "#3366cc"}
      effects:
        - {name: drop-shadow, params: {dx: 0pt, dy: 0pt, blur: 20pt, color: "#000000"}}
      constraints:
        anchor: {top: parent.top+20pt, left: parent.left+20pt}
        size: {w: 100pt, h: 40pt}

    - id: tag
      type: shape
      shape: rect
      style: {fill: "#cc3366"}
      constraints:
        anchor: {top: parent.top+20pt, left: strip.right+10pt}
        size: {w: 100pt, h: 40pt}

    - id: venue-1
      type: text
      text: "First venue line"
      style: {font: Inter, font_size: 14pt, color: "#000000"}
      constraints:
        anchor: {top: parent.top+200pt, left: parent.left+20pt}
        size: {w: 200pt, h: 40pt}

    - id: venue-2
      type: text
      text: "Second venue line"
      style: {font: Inter, font_size: 14pt, color: "#000000"}
      constraints:
        anchor: {top: venue-1.bottom-4pt, left: parent.left+20pt}
        size: {w: 200pt, h: 40pt}
"""


def _template(tmp_path: Path) -> str:
    path = tmp_path / "overlaps.yaml"
    path.write_text(_TEMPLATE, encoding="utf-8")
    return str(path)


def test_layout_inspect_result_carries_overlap_kind(tools: ArcavexTools, tmp_path: Path) -> None:
    report = tools.layout_inspect(_template(tmp_path), format="sq")
    assert report.ok, report.diagnostics
    by_pair = {frozenset((ov.a, ov.b)): ov.kind for ov in report.overlaps}
    assert by_pair == {
        frozenset(("strip", "tag")): "halo",
        frozenset(("venue-1", "venue-2")): "content",
    }


def test_agent_filters_to_the_one_real_collision(tools: ArcavexTools, tmp_path: Path) -> None:
    """The payoff: one structural filter, no heuristics and no vision, finds the genuine bug."""
    report = tools.layout_inspect(_template(tmp_path), format="sq")
    actionable = [ov for ov in report.overlaps if ov.kind == "content"]
    assert len(actionable) == 1
    (ov,) = actionable
    assert {ov.a, ov.b} == {"venue-1", "venue-2"}
    # The rect is the collision itself, so its height is the correction to apply.
    assert round(ov.rect_pt[3], 1) == 4.0


def test_overlap_kind_survives_real_server_dispatch(server: FastMCP, tmp_path: Path) -> None:
    """The field is present in the structured content FastMCP actually hands the agent."""

    async def call() -> object:
        return await server.call_tool(
            "arcavex_layout_inspect", {"template": _template(tmp_path), "format": "sq"}
        )

    payload = json.dumps(asyncio.run(call()), default=str)
    assert "ARC-INT-999" not in payload
    assert '"kind": "halo"' in payload or "'kind': 'halo'" in payload
    assert '"kind": "content"' in payload or "'kind': 'content'" in payload

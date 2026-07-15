"""Shared fixtures for the MCP scripted-agent sessions.

These tests exercise the MCP authoring surface the way an agent would: through the same tool
callables the server registers, with an isolated ``$ARCAVEX_HOME`` so nothing touches the real
library or asset store. A session drives structured tool results only — it never scrapes text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.clients.mcp_server import ArcavexTools, build_mcp_server

_BROKEN_TEMPLATE = """\
version: 0.1.0

# A deliberately broken poster: the background fill is not a valid color, so the template
# fails validation until an agent corrects it with a single addressed patch.
variables:
  title: {type: string, required: true, doc: "Headline"}

formats:
  poster:
    canvas: {width: 800px, height: 800px, dpi: 96}

preview_data:
  title: "Correct Me"

root:
  type: group
  id: root
  children:
    - id: background
      type: shape
      shape: rect
      style: {fill: "not-a-color"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}

    - id: title
      type: text
      text: "{{ title }}"
      style: {font: Inter, font_size: 64px, font_weight: 800, color: "#ffffff", align: center}
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 80%, h: fit_content}
"""


@pytest.fixture()
def tools(arcavex_home: Path) -> ArcavexTools:
    """An :class:`ArcavexTools` over a facade with an isolated home (library/assets/cache)."""
    return ArcavexTools(build_facade())


@pytest.fixture()
def server(arcavex_home: Path):
    """A fully built FastMCP server over an isolated-home facade (for call_tool smoke tests)."""
    return build_mcp_server(build_facade())


@pytest.fixture()
def scaffold(tools: ArcavexTools, tmp_path: Path) -> Path:
    """A freshly scaffolded, self-contained template directory (no external assets)."""
    target = tmp_path / "card"
    result = tools._facade.scaffold_template("card", target)
    assert result.ok, result.diagnostics
    return target


@pytest.fixture()
def broken_template(tmp_path: Path) -> Path:
    """A template directory whose background fill is an invalid color (fails validation)."""
    target = tmp_path / "poster"
    target.mkdir()
    (target / "template.yaml").write_text(_BROKEN_TEMPLATE, encoding="utf-8")
    return target

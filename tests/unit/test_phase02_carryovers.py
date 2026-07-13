"""Phase 1 carry-over fixes verified in Phase 2 (RR1-1, RR1-2)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from arcavex.services.template.compiler import Compiler

_HEADER = """
version: 0.1.0
variables: {items: {type: list, default: [{id: a, show: true}, {id: b, show: false}]}}
formats: {square: {canvas: {width: 200px, height: 200px, dpi: 72}}}
root:
  type: group
  id: root
  children:
"""


def test_tpl061_hint_wrapper_group_form_compiles(tmp_path: Path) -> None:
    """RR1-1: the corrected ARC-TPL-061 hint recommends a wrapper group; it must compile."""
    template = tmp_path / "t.yaml"
    template.write_text(
        _HEADER
        + """
    - repeat: "{{ items }}"
      as: item
      key: "{{ item.id }}"
      node:
        type: group
        id: wrapper
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
        children:
          - if: "{{ item.show }}"
            node:
              id: card
              type: shape
              shape: rect
              constraints:
                anchor: {top: parent.top, left: parent.left}
                size: {w: 10pt, h: 10pt}
""",
        encoding="utf-8",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None, result.diagnostics
    # item 'a' (show true) instantiates the card; item 'b' (show false) drops it.
    ids = {c.id for c in result.document.root.children}
    assert "wrapper[a]" in ids and "wrapper[b]" in ids
    a_wrapper = next(c for c in result.document.root.children if c.id == "wrapper[a]")
    b_wrapper = next(c for c in result.document.root.children if c.id == "wrapper[b]")
    assert len(a_wrapper.children) == 1  # card kept
    assert len(b_wrapper.children) == 0  # card dropped


def test_inspect_escapes_construct_tags(tmp_path: Path) -> None:
    """RR1-2: 'template inspect' human output shows literal [if]/[repeat] origin tags."""
    template = tmp_path / "t.yaml"
    template.write_text(
        _HEADER
        + """
    - if: "{{ items }}"
      node:
        id: gated
        type: shape
        shape: rect
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 5pt, h: 5pt}}
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", "template", "inspect", str(template)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    # The literal '[if]' tag survives Rich markup rendering (it would vanish unescaped).
    assert "[if]" in proc.stdout


def test_inspect_json_still_reports_origin(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    template.write_text(
        _HEADER
        + """
    - if: "{{ items }}"
      node:
        id: gated
        type: shape
        shape: rect
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 5pt, h: 5pt}}
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", "template", "inspect", str(template),
         "--json"],
        capture_output=True, text=True, encoding="utf-8",
    )
    payload = json.loads(proc.stdout)
    gated = next(n for n in payload["nodes"] if n["id"] == "gated")
    assert gated["origin"] == "if"

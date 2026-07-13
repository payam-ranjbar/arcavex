"""Phase 2 layout tests: sibling anchors, logical directions, stacks, aspect, rotation."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.builtin.layout_anchors import AnchorLayoutSolver
from arcavex.kernel.contracts.types import MeasureRequest, MeasureResult
from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.kernel.ir.models import LayoutNode
from arcavex.services.template.compiler import Compiler


def fake_measure(req: MeasureRequest) -> MeasureResult:
    width = len(req.text) * req.font_size_pt * 0.5
    if req.max_width_pt is not None:
        width = min(width, req.max_width_pt)
    return MeasureResult(
        width_pt=width, height_pt=req.font_size_pt * 1.2, baseline_pt=req.font_size_pt,
        line_count=1, resolved_size_pt=req.font_size_pt,
    )


HEADER = """
version: 0.1.0
formats:
  square: {canvas: {width: 400px, height: 400px, dpi: 72}}
root:
  type: group
  id: root
"""


def _solve(tmp_path: Path, body: str, direction: str = "ltr"):  # noqa: ANN202
    template = tmp_path / "t.yaml"
    dir_line = f"  direction: {direction}\n" if direction != "ltr" else ""
    template.write_text(HEADER + dir_line + body, encoding="utf-8")
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None, result.diagnostics
    return AnchorLayoutSolver().solve(result.document, fake_measure)


def _find(node: LayoutNode, node_id: str) -> LayoutNode:
    if node.source_node_id == node_id:
        return node
    for child in node.children:
        found = _find_opt(child, node_id)
        if found is not None:
            return found
    raise AssertionError(f"{node_id} not found")


def _find_opt(node: LayoutNode, node_id: str) -> LayoutNode | None:
    if node.source_node_id == node_id:
        return node
    for child in node.children:
        found = _find_opt(child, node_id)
        if found is not None:
            return found
    return None


def test_sibling_anchor_below(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
  children:
    - id: a
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top+10pt, left: parent.left+10pt}
        size: {w: 100pt, h: 50pt}
    - id: b
      type: shape
      shape: rect
      constraints: {anchor: {top: a.bottom+8pt, left: a.left}, size: {w: 100pt, h: 40pt}}
""",
    )
    b = _find(layout.root, "b")
    assert (b.bounds.x, b.bounds.y) == (10.0, 68.0)  # a.bottom (60) + 8


def test_logical_start_ltr_and_rtl(tmp_path: Path) -> None:
    body = """
  children:
    - id: box
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, start: parent.start+20pt}, size: {w: 80pt, h: 40pt}}
"""
    ltr = _find(_solve(tmp_path, body, "ltr").root, "box")
    assert ltr.bounds.x == 20.0  # start=left, +20 inward
    rtl = _find(_solve(tmp_path, body, "rtl").root, "box")
    # start=right in rtl; the node's right edge sits 20pt in from the parent's right (400-20=380)
    assert rtl.bounds.right == 380.0
    assert rtl.bounds.x == 300.0


def test_hstack_distributes_with_fill(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
  children:
    - id: bar
      type: group
      layout: hstack
      gap: 10pt
      cross_align: center
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: 100pt}}
      children:
        - id: x
          type: shape
          shape: rect
          constraints: {size: {w: 50pt, h: 30pt}}
        - id: y
          type: shape
          shape: rect
          constraints: {size: {w: fill, h: 30pt}}
""",
    )
    x = _find(layout.root, "x")
    y = _find(layout.root, "y")
    assert x.bounds.x == 0.0 and x.bounds.w == 50.0
    assert y.bounds.x == 60.0  # 50 + gap 10
    assert y.bounds.w == 340.0  # 400 - 50 - 10 gap
    assert x.bounds.y == 35.0  # cross center in 100pt band for a 30pt child


def test_vstack_stacks_children(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
  children:
    - id: col
      type: group
      layout: vstack
      gap: 6pt
      padding: 10pt
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 200pt, h: fill}}
      children:
        - id: a
          type: shape
          shape: rect
          constraints: {size: {w: 100pt, h: 40pt}}
        - id: b
          type: shape
          shape: rect
          constraints: {size: {w: 100pt, h: 40pt}}
""",
    )
    a = _find(layout.root, "a")
    b = _find(layout.root, "b")
    assert a.bounds.y == 10.0  # padding
    assert b.bounds.y == 56.0  # 10 pad + 40 + 6 gap


def test_aspect_derives_from_other_axis(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
  children:
    - id: img
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 120pt, h: {aspect: "3:4"}}
""",
    )
    img = _find(layout.root, "img")
    assert img.bounds.w == 120.0 and img.bounds.h == 160.0  # h = w * 4/3


def test_min_max_clamp(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
  children:
    - id: box
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: {value: 10%, min: 100pt}, h: {value: 90%, max: 120pt}}
""",
    )
    box = _find(layout.root, "box")
    assert box.bounds.w == 100.0  # 10% of 400 = 40, clamped up to min 100
    assert box.bounds.h == 120.0  # 90% of 400 = 360, clamped down to max 120


def test_rotation_expands_paint_bounds(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
  children:
    - id: r
      type: shape
      shape: rect
      transform: {rotate: 45, origin: center}
      constraints:
        anchor: {top: parent.top+100pt, left: parent.left+100pt}
        size: {w: 100pt, h: 100pt}
""",
    )
    r = _find(layout.root, "r")
    assert r.bounds.w == 100.0  # layout bounds unaffected
    assert r.rotate_deg == 45.0
    assert r.paint_bounds.w > 140.0  # AABB of a 45-rotated 100pt square ~ 141.4


def test_sibling_cycle_named(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError) as exc:
        _solve(
            tmp_path,
            """
  children:
    - id: n1
      type: shape
      shape: rect
      constraints: {anchor: {top: n2.bottom, left: parent.left}, size: {w: 10pt, h: 10pt}}
    - id: n2
      type: shape
      shape: rect
      constraints: {anchor: {top: n1.bottom, left: parent.left}, size: {w: 10pt, h: 10pt}}
""",
        )
    diag = exc.value.diagnostics[0]
    assert diag.code == "ARC-LAY-052"
    assert "n1" in diag.message and "n2" in diag.message


def test_unknown_sibling_anchor(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError) as exc:
        _solve(
            tmp_path,
            """
  children:
    - id: a
      type: shape
      shape: rect
      constraints: {anchor: {top: ghost.bottom, left: parent.left}, size: {w: 10pt, h: 10pt}}
""",
        )
    assert exc.value.diagnostics[0].code == "ARC-LAY-053"


def test_stack_child_with_anchor_errors(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError) as exc:
        _solve(
            tmp_path,
            """
  children:
    - id: col
      type: group
      layout: vstack
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
      children:
        - id: a
          type: shape
          shape: rect
          constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
""",
        )
    assert exc.value.diagnostics[0].code == "ARC-LAY-054"


def test_aspect_on_both_axes_errors(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError) as exc:
        _solve(
            tmp_path,
            """
  children:
    - id: a
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: {aspect: "1:1"}, h: {aspect: "1:1"}}
""",
        )
    assert exc.value.diagnostics[0].code == "ARC-LAY-055"

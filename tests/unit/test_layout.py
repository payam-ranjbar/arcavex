"""Anchor layout solver tests: resolution and constraint errors."""

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
        width_pt=width,
        height_pt=req.font_size_pt * 1.2,
        baseline_pt=req.font_size_pt,
        line_count=1,
        resolved_size_pt=req.font_size_pt,
    )


def _compile(tmp_path: Path, body: str):  # noqa: ANN202
    template = tmp_path / "t.yaml"
    template.write_text(body, encoding="utf-8")
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None, result.diagnostics
    return result.document


def _find(node: LayoutNode, node_id: str) -> LayoutNode:
    result = _find_opt(node, node_id)
    assert result is not None, f"{node_id} not found"
    return result


def _find_opt(node: LayoutNode, node_id: str) -> LayoutNode | None:
    if node.source_node_id == node_id:
        return node
    for child in node.children:
        found = _find_opt(child, node_id)
        if found is not None:
            return found
    return None


HEADER = """
version: 0.1.0
formats:
  square: {canvas: {width: 400px, height: 400px, dpi: 96}}
root:
  type: group
  id: root
  children:
"""


def test_fill_and_percent_and_center(tmp_path: Path) -> None:
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: bg
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
    - id: box
      type: shape
      shape: rect
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 50%, h: 20%}
""",
    )
    layout = AnchorLayoutSolver().solve(doc, fake_measure)
    bg = _find(layout.root, "bg")
    assert (bg.bounds.x, bg.bounds.y, bg.bounds.w, bg.bounds.h) == (0.0, 0.0, 300.0, 300.0)
    box = _find(layout.root, "box")
    # canvas is 300pt; 50% width = 150, centered -> x = 75
    assert box.bounds.w == 150.0
    assert box.bounds.x == 75.0
    assert box.bounds.h == 60.0


def test_anchor_offset(tmp_path: Path) -> None:
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: box
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top+48px, left: parent.left+48px}
        size: {w: 100px, h: 100px}
""",
    )
    layout = AnchorLayoutSolver().solve(doc, fake_measure)
    box = _find(layout.root, "box")
    # 48px @96dpi = 36pt
    assert box.bounds.x == 36.0
    assert box.bounds.y == 36.0
    assert box.bounds.w == 75.0  # 100px -> 75pt


def test_fit_content_text(tmp_path: Path) -> None:
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: label
      type: text
      text: "abcd"
      style: {font: Inter, font_size: 20px}
      constraints:
        anchor: {left: parent.left, top: parent.top}
        size: {w: fit_content, h: fit_content}
""",
    )
    layout = AnchorLayoutSolver().solve(doc, fake_measure)
    label = _find(layout.root, "label")
    # font_size 20px -> 15pt; width = 4 * 15 * 0.5 = 30, plus the 0.5pt fit_content safety
    # margin that keeps quantization from forcing a spurious character wrap.
    assert label.bounds.w == 30.5
    assert round(label.bounds.h, 3) == round(15.0 * 1.2, 3)


def test_over_constrained_horizontal(tmp_path: Path) -> None:
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: bad
      type: shape
      shape: rect
      constraints:
        anchor: {left: parent.left, right: parent.right, top: parent.top}
        size: {w: 50%, h: 50%}
""",
    )
    with pytest.raises(DiagnosticError) as exc:
        AnchorLayoutSolver().solve(doc, fake_measure)
    assert exc.value.diagnostics[0].code == "ARC-LAY-031"


def test_under_constrained_horizontal(tmp_path: Path) -> None:
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: bad
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top}
        size: {w: 50%, h: 50%}
""",
    )
    with pytest.raises(DiagnosticError) as exc:
        AnchorLayoutSolver().solve(doc, fake_measure)
    assert exc.value.diagnostics[0].code == "ARC-LAY-030"


def test_visible_false_carried_into_layout(tmp_path: Path) -> None:
    """CR-2: an authored 'visible: false' is honored as explicit state on the layout node."""
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: hidden
      type: shape
      shape: rect
      visible: false
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
    - id: shown
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
""",
    )
    layout = AnchorLayoutSolver().solve(doc, fake_measure)
    assert _find(layout.root, "hidden").visible is False
    assert _find(layout.root, "shown").visible is True


def test_fit_content_on_shape_errors(tmp_path: Path) -> None:
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: bad
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fit_content, h: fill}
""",
    )
    with pytest.raises(DiagnosticError) as exc:
        AnchorLayoutSolver().solve(doc, fake_measure)
    assert exc.value.diagnostics[0].code == "ARC-LAY-020"


def test_fill_with_an_offset_warns_about_the_overshoot(tmp_path: Path) -> None:
    """'fill' spans the whole parent, so an offset pushes it out by that amount (ARC-LAY-033)."""
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: frame
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top+24px, left: parent.left+24px}
        size: {w: fill, h: fill}
""",
    )
    layout = AnchorLayoutSolver().solve(doc, fake_measure)
    assert [w.code for w in layout.warnings] == ["ARC-LAY-033", "ARC-LAY-033"]
    horizontal, vertical = layout.warnings
    assert horizontal.severity == "warning"
    assert "horizontal" in horizontal.message and "18.00pt" in horizontal.message  # 24px @96
    assert "vertical" in vertical.message
    assert horizontal.hint is not None
    assert "percentage" in horizontal.hint and "vstack" in horizontal.hint
    assert horizontal.source is not None and horizontal.source.keypath is not None
    # The render is not refused: the node still resolves to the overshooting box.
    frame = _find(layout.root, "frame")
    assert (frame.bounds.x, frame.bounds.w) == (18.0, 300.0)


def test_fill_anchored_flush_does_not_warn(tmp_path: Path) -> None:
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: bg
      type: shape
      shape: rect
      constraints:
        anchor: {bottom: parent.bottom, right: parent.right}
        size: {w: fill, h: fill}
    - id: inset
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top+24px, left: parent.left+24px}
        size: {w: 80%, h: 80%}
""",
    )
    layout = AnchorLayoutSolver().solve(doc, fake_measure)
    assert layout.warnings == ()


def test_over_constrained_hint_names_the_span_and_inset_idioms(tmp_path: Path) -> None:
    """An author who writes left+right wants both edges; the refusal must say how to get them."""
    doc = _compile(
        tmp_path,
        HEADER
        + """
    - id: frame
      type: shape
      shape: rect
      constraints:
        anchor: {left: parent.left+24px, right: parent.right-24px, top: parent.top}
        size: {w: 50%, h: 50%}
""",
    )
    with pytest.raises(DiagnosticError) as exc:
        AnchorLayoutSolver().solve(doc, fake_measure)
    diag = exc.value.diagnostics[0]
    assert diag.code == "ARC-LAY-031" and diag.hint is not None
    assert "size: {w: fill}" in diag.hint and "percentage" in diag.hint and "vstack" in diag.hint

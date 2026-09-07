"""Layout inspection report tests (spec §6.1.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import LayoutNodeReport

_REPO = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO / "tests" / "fixtures" / "bilingual-poster" / "template.yaml"
_DATA = _REPO / "tests" / "fixtures" / "bilingual-poster" / "data.yaml"


def _find(node: LayoutNodeReport, node_id: str) -> LayoutNodeReport:
    if node.id == node_id:
        return node
    for child in node.children:
        found = _find_opt(child, node_id)
        if found is not None:
            return found
    raise AssertionError(f"{node_id} not found")


def _find_opt(node: LayoutNodeReport, node_id: str) -> LayoutNodeReport | None:
    if node.id == node_id:
        return node
    for child in node.children:
        found = _find_opt(child, node_id)
        if found is not None:
            return found
    return None


def test_report_has_versioned_structure() -> None:
    report = build_facade().inspect_layout(_TEMPLATE, _DATA, "square", "fa")
    assert report.ok
    assert report.response_version >= 1
    assert report.canvas_px == (1080, 1080)
    assert report.dpi == 96
    assert report.root is not None


def test_anchor_derivation_reported() -> None:
    report = build_facade().inspect_layout(_TEMPLATE, _DATA, "square", "en")
    assert report.root is not None
    title = _find(report.root, "title")
    exprs = {a.expression for a in title.anchors}
    # The title anchors vertically to the accent bar (a sibling) — the chain is reported.
    assert any("accent-bar" in e for e in exprs)


def test_pt_and_px_bounds_scale_by_dpi() -> None:
    report = build_facade().inspect_layout(_TEMPLATE, _DATA, "square", "en")
    assert report.root is not None
    hero = _find(report.root, "hero")
    # px = pt * dpi/72; square is 96 dpi.
    assert abs(hero.bounds_px[2] - hero.bounds_pt[2] * 96 / 72) < 0.01


def test_stack_children_report_stack_positioning() -> None:
    report = build_facade().inspect_layout(_TEMPLATE, _DATA, "square", "en")
    assert report.root is not None
    day = _find(report.root, "date-day")
    assert any("vstack" in a.expression for a in day.anchors)


def test_overlaps_suppress_full_bleed_background() -> None:
    # DX-8: the full-bleed background fully contains every sibling, so those trivially-true
    # overlaps are suppressed as noise (the genuine partial collisions stay).
    report = build_facade().inspect_layout(_TEMPLATE, _DATA, "square", "en")
    assert not any(o.a == "background" or o.b == "background" for o in report.overlaps)
    assert 0.0 < report.covered_fraction <= 1.0


def test_report_carries_transform_and_paint_px() -> None:
    # CR-15: absolute_transform and paint_bounds_px are surfaced per node.
    report = build_facade().inspect_layout(_TEMPLATE, _DATA, "square", "en")
    assert report.root is not None
    accent = _find(report.root, "accent-bar")  # rotated node
    assert accent.rotate_deg != 0.0
    assert accent.absolute_transform != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    assert accent.paint_bounds_px[2] > 0.0


def test_rotated_descendants_use_canvas_space_in_layout_summaries(tmp_path: Path) -> None:
    """Overlap, coverage, and free regions must share reported node coordinates."""
    template = tmp_path / "rotated-summary.yaml"
    template.write_text(
        """version: 0.1.0
formats:
  sq: {canvas: {width: 300pt, height: 200pt, dpi: 72}}
root:
  id: root
  type: group
  children:
    - id: outer
      type: group
      transform: {rotate: 90, origin: center}
      constraints:
        anchor: {top: parent.top+40pt, left: parent.left+40pt}
        size: {w: 100pt, h: 100pt}
      children:
        - id: a
          type: shape
          shape: rect
          constraints:
            anchor: {top: parent.top, left: parent.left}
            size: {w: 50pt, h: 50pt}
        - id: b
          type: shape
          shape: rect
          constraints:
            anchor: {top: parent.top, left: parent.left+30pt}
            size: {w: 50pt, h: 50pt}
""",
        encoding="utf-8",
    )

    report = build_facade().inspect_layout(template, format_name="sq")

    assert report.ok, [diagnostic.model_dump() for diagnostic in report.diagnostics]
    assert report.root is not None
    a = _find(report.root, "a")
    b = _find(report.root, "b")
    assert a.bounds_pt == pytest.approx((90.0, 40.0, 50.0, 50.0))
    assert b.bounds_pt == pytest.approx((90.0, 70.0, 50.0, 50.0))
    overlap = next(
        item for item in report.overlaps if {item.a, item.b} == {"a", "b"}
    )
    assert overlap.rect_pt == pytest.approx((90.0, 70.0, 50.0, 20.0))
    assert report.covered_fraction == pytest.approx(round(297 / (64 * 64), 4))
    assert report.free_regions == [
        (0.0, 121.88, 300.0, 78.12),
        (0.0, 0.0, 300.0, 37.5),
    ]


def test_inspect_failure_reports_diagnostics(tmp_path: Path) -> None:
    bad = tmp_path / "t.yaml"
    bad.write_text("version: 0.1.0\nroot: {type: group, id: root}\n", encoding="utf-8")
    report = build_facade().inspect_layout(bad, None, None, None)
    assert not report.ok
    assert report.diagnostics

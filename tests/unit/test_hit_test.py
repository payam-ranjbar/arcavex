"""Geometry hit-test contract and behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from arcavex.bootstrap import build_facade
from arcavex.kernel import api


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "hit-campaign"
    template = project / "template"
    template.mkdir(parents=True)
    (project / "project.yaml").write_text(
        "name: hits\ntemplate: ./template\nformats: [square]\nlocales: [en]\n"
        "data: data.yaml\n",
        encoding="utf-8",
    )
    (project / "project.ui.yaml").write_text(
        "version: 1\nlayers:\n  foreground: {locked: true}\n  panel: {locked: true}\n",
        encoding="utf-8",
    )
    (project / "data.yaml").write_text(
        "cards: [{id: alpha}, {id: beta}]\n", encoding="utf-8"
    )
    (template / "template.yaml").write_text(
        """version: 0.1.0
variables:
  cards: {type: list, default: []}
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 72}}
locales:
  en: {direction: ltr, digits: en}
root:
  id: root
  type: group
  children:
    - id: background
      type: shape
      shape: rect
      z: -1
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
    - id: panel
      type: group
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 50pt, h: 50pt}}
      children:
        - id: nested
          type: shape
          shape: rect
          z: 100
          constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 20pt, h: 20pt}}
    - repeat: "{{ cards }}"
      as: card
      key: "{{ card.id }}"
      node:
        id: card
        type: shape
        shape: rect
        z: 2
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 30pt, h: 30pt}}
    - id: foreground
      type: shape
      shape: rect
      z: 10
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 40pt, h: 40pt}}
    - id: invisible
      type: shape
      shape: rect
      visible: false
      z: 20
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 60pt, h: 60pt}}
    - id: hidden-group
      type: group
      visible: false
      z: 30
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 70pt, h: 70pt}}
      children:
        - id: hidden-child
          type: shape
          shape: rect
          constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 60pt, h: 60pt}}
""",
        encoding="utf-8",
    )
    return project


def test_hit_test_contract_uses_canvas_points_and_shared_candidates() -> None:
    """Accepting pixels as canonical input or dropping either identity must break the contract."""
    candidate_type = getattr(api, "HitCandidate", None)
    report_type = getattr(api, "HitTestReport", None)

    assert candidate_type is not None
    assert report_type is not None
    candidate = candidate_type(
        id="card[alpha]",
        authored_id="card",
        instance_id="card[alpha]",
        parent_id="root",
        kind="shape",
        display_name="Feature card",
        editable=False,
        locked=True,
        bounds_pt=(10.0, 20.0, 30.0, 40.0),
        paint_bounds_pt=(8.0, 18.0, 34.0, 44.0),
    )
    report = report_type(
        ok=True,
        format="square",
        locale="en",
        point_pt=(12.0, 24.0),
        point_px=(24.0, 48.0),
        candidates=[candidate],
    )

    assert report.model_dump(mode="json") == {
        "response_version": 1,
        "ok": True,
        "format": "square",
        "locale": "en",
        "point_pt": [12.0, 24.0],
        "point_px": [24.0, 48.0],
        "candidates": [
            {
                "id": "card[alpha]",
                "authored_id": "card",
                "instance_id": "card[alpha]",
                "parent_id": "root",
                "kind": "shape",
                "display_name": "Feature card",
                "editable": False,
                "locked": True,
                "bounds_pt": [10.0, 20.0, 30.0, 40.0],
                "paint_bounds_pt": [8.0, 18.0, 34.0, 44.0],
            }
        ],
        "diagnostics": [],
    }
    with pytest.raises(ValidationError):
        report.point_pt = (0.0, 0.0)
    with pytest.raises(ValidationError):
        report_type(ok=True, point_pt=(float("nan"), 0.0))
    with pytest.raises(ValidationError):
        candidate_type(
            id="bad",
            authored_id="bad",
            instance_id="bad",
            kind="shape",
            display_name="Bad",
            editable=True,
            locked=False,
            bounds_pt=(0.0, 0.0, float("inf"), 1.0),
            paint_bounds_pt=(0.0, 0.0, 1.0, 1.0),
        )


def test_hit_test_returns_reverse_paint_containment_and_keeps_locked_candidates(
    tmp_path: Path,
) -> None:
    """Source order, invisible hits, or dropping locked layers must fail selection."""
    facade = build_facade()

    report = facade.hit_test(
        project=_project(tmp_path),
        x_pt=10.0,
        y_pt=10.0,
        format_name="square",
        locale="en",
    )

    assert report.ok, [diagnostic.model_dump() for diagnostic in report.diagnostics]
    assert report.point_pt == (10.0, 10.0)
    assert report.point_px == (10.0, 10.0)
    assert [candidate.id for candidate in report.candidates] == [
        "foreground",
        "card[beta]",
        "card[alpha]",
        "nested",
        "panel",
        "background",
        "root",
    ]
    assert "invisible" not in {candidate.id for candidate in report.candidates}
    assert "hidden-group" not in {candidate.id for candidate in report.candidates}
    assert "hidden-child" not in {candidate.id for candidate in report.candidates}
    foreground = report.candidates[0]
    assert (foreground.authored_id, foreground.instance_id) == ("foreground", "foreground")
    assert (foreground.locked, foreground.editable) == (True, False)
    nested = next(candidate for candidate in report.candidates if candidate.id == "nested")
    assert (nested.locked, nested.editable) == (True, False)


def test_rendered_tree_reports_effective_ancestor_visibility_and_lock_state(
    tmp_path: Path,
) -> None:
    """Locally-visible children must inherit hidden and locked ancestor restrictions."""
    tree = build_facade().layer_tree(
        project=_project(tmp_path), mode="rendered", format_name="square", locale="en"
    )
    assert tree.root is not None
    root_children = {child.id: child for child in tree.root.children}
    hidden_child = root_children["hidden-group"].children[0]
    nested = root_children["panel"].children[0]

    assert (hidden_child.visible, hidden_child.hit_testable) == (False, False)
    assert (nested.locked, nested.editable) == (True, False)


def test_hit_test_outside_canvas_returns_no_candidates(tmp_path: Path) -> None:
    """A point outside every paint AABB must not select a fallback/root layer."""
    report = build_facade().hit_test(
        project=_project(tmp_path), x_pt=-1.0, y_pt=-1.0, format_name="square", locale="en"
    )

    assert report.ok
    assert report.candidates == []


def test_facade_invalid_hit_points_return_one_stable_input_diagnostic(
    tmp_path: Path,
) -> None:
    """Conversion errors and non-finite floats must never escape the Facade boundary."""
    facade = build_facade()
    project = _project(tmp_path)

    for invalid in ("not-a-number", float("nan"), float("inf"), float("-inf")):
        report = facade.hit_test(  # type: ignore[arg-type]
            project=project,
            x_pt=invalid,
            y_pt=0.0,
            format_name="square",
            locale="en",
        )

        assert not report.ok
        assert report.point_pt == (0.0, 0.0)
        assert report.point_px is None
        assert report.candidates == []
        assert [diagnostic.code for diagnostic in report.diagnostics] == ["ARC-IR-015"]


def test_zero_effective_opacity_suppresses_hits_without_changing_visibility(
    tmp_path: Path,
) -> None:
    """A transparent group must suppress its branch while positive opacity still paints."""
    project = _project(tmp_path)
    template = project / "template" / "template.yaml"
    template.write_text(
        template.read_text(encoding="utf-8")
        .replace(
            "id: background\n      type: shape",
            "id: background\n      type: shape\n      style: {opacity: 0.25}",
        )
        .replace(
            "id: panel\n      type: group",
            "id: panel\n      type: group\n      style: {opacity: 0}",
        )
        .replace(
            "id: foreground\n      type: shape",
            "id: foreground\n      type: shape\n      style: {opacity: 0}",
        ),
        encoding="utf-8",
    )
    facade = build_facade()

    tree = facade.layer_tree(
        project=project,
        mode="rendered",
        format_name="square",
        locale="en",
    )
    hit = facade.hit_test(
        project=project,
        x_pt=10.0,
        y_pt=10.0,
        format_name="square",
        locale="en",
    )

    assert tree.root is not None
    by_id = {row.id: row for row in tree.root.children}
    nested = by_id["panel"].children[0]
    assert (by_id["foreground"].visible, by_id["foreground"].hit_testable) == (True, False)
    assert (by_id["panel"].visible, by_id["panel"].hit_testable) == (True, False)
    assert (nested.visible, nested.hit_testable) == (True, False)
    candidate_ids = {candidate.id for candidate in hit.candidates}
    assert {"foreground", "panel", "nested"}.isdisjoint(candidate_ids)
    assert "background" in candidate_ids

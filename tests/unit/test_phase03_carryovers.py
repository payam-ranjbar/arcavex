"""Regression tests for the phase-02 re-review carry-overs (RR2-4 .. RR2-12)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201
    return build_facade()


def _write(tmp_path: Path, text: str, name: str = "t.yaml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------------- RR2-4
def test_rr2_4_template_yaml_from_own_dir_uses_dir_name(facade, tmp_path) -> None:  # noqa: ANN001
    """Rendering 'template.yaml' from inside its directory names the file after the dir."""
    d = tmp_path / "poster"
    d.mkdir()
    (d / "template.yaml").write_text(
        "formats: {square: {canvas: {width: 32px, height: 32px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n      style: {fill: '#000000'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}\n",
        encoding="utf-8",
    )
    cwd = os.getcwd()
    try:
        os.chdir(d)
        plan = facade.render_plan(Path("template.yaml"))
    finally:
        os.chdir(cwd)
    out = plan.get("output", "")
    assert out and not out.startswith("."), out
    assert out.startswith("poster.")


# ------------------------------------------------------------------- RR2-8
def test_rr2_8_fill_clamp_redistributes(facade, tmp_path) -> None:  # noqa: ANN001
    """A capped fill child gives its surplus to the other fill child in a stack."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 300px, height: 100px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  layout: hstack\n  children:\n"
        "    - id: capped\n      type: shape\n      shape: rect\n      style: {fill: '#f00'}\n"
        "      constraints: {size: {w: {value: fill, max: 40px}, h: fill}}\n"
        "    - id: greedy\n      type: shape\n      shape: rect\n      style: {fill: '#00f'}\n"
        "      constraints: {size: {w: fill, h: fill}}\n",
    )
    report = facade.inspect_layout(template, format_name="sq")
    assert report.ok, [d.code for d in report.diagnostics]
    by_id = {c.id: c for c in report.root.children}
    capped_w = by_id["capped"].bounds_pt[2]
    greedy_w = by_id["greedy"].bounds_pt[3 - 1]  # width is index 2
    # Canvas 300px = 225pt. capped is clamped at 40px = 30pt; greedy absorbs the rest.
    assert capped_w == pytest.approx(30.0, abs=0.5)
    assert greedy_w > 150.0  # got the freed space, not just half


# ------------------------------------------------------------------- RR2-9
def test_rr2_9_backdrop_containment_suppressed_but_content_reported(facade, tmp_path) -> None:  # noqa: ANN001
    """A full-bleed backdrop enclosing a node is not an overlap; a content node swallowing a
    sibling still is."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 200px, height: 200px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: bg\n      type: shape\n      shape: rect\n      style: {fill: '#eee'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: 100%, h: 100%}}\n"
        "    - id: panel\n      type: shape\n      shape: rect\n      style: {fill: '#f0f'}\n"
        "      constraints: {anchor: {left: parent.left+40px, top: parent.top+40px}, "
        "size: {w: 100px, h: 100px}}\n"
        "    - id: swallowed\n      type: shape\n      shape: rect\n      style: {fill: '#0ff'}\n"
        "      constraints: {anchor: {left: parent.left+60px, top: parent.top+60px}, "
        "size: {w: 40px, h: 40px}}\n",
    )
    report = facade.inspect_layout(template, format_name="sq")
    assert report.ok, [d.code for d in report.diagnostics]
    pairs = {frozenset((o.a, o.b)) for o in report.overlaps}
    # The full-bleed backdrop enclosing others is suppressed as noise.
    assert frozenset(("bg", "panel")) not in pairs
    assert frozenset(("bg", "swallowed")) not in pairs
    # A regular panel fully swallowing a sibling is a genuine bug and is still reported.
    assert frozenset(("panel", "swallowed")) in pairs


# ------------------------------------------------------------------- RR2-10
def test_rr2_10_resolved_records_losing_layer_value(facade, tmp_path) -> None:  # noqa: ANN001
    """Two set ops on one path: the overridden op reports the value *it* set, not the winner's."""
    template = _write(
        tmp_path,
        "formats:\n"
        "  sq:\n"
        "    canvas: {width: 64px, height: 64px, dpi: 96}\n"
        "    patch:\n"
        "      - set: nodes.s.style.fill\n        value: '#111111'\n"
        "      - set: nodes.s.style.fill\n        value: '#222222'\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n      style: {fill: '#000000'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}\n",
    )
    report = facade.inspect_resolved(template, None, "sq", None)
    assert report.ok
    fill_ops = [p for p in report.patches if p.path == "nodes.s.style.fill"]
    assert len(fill_ops) == 2
    assert fill_ops[0].value == "#111111" and not fill_ops[0].effective  # losing layer's value
    assert fill_ops[1].value == "#222222" and fill_ops[1].effective


# ------------------------------------------------------------------- RR2-12
def test_rr2_12_unknown_field_hint_excludes_line_height(facade, tmp_path) -> None:  # noqa: ANN001
    """The ARC-TPL-051 'valid fields' hint no longer lists the rejected 'line_height'."""
    unknown = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n      style: {bogus: 1}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}\n",
        name="u.yaml",
    )
    diags = facade.validate_template(unknown, format_name="sq")
    d = next(d for d in diags if d.code == "ARC-TPL-051")
    assert "line_height" not in (d.hint or "")

    lh = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 200px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: t\n      type: text\n      text: hi\n"
        "      style: {font: Inter, font_size: 12pt, line_height: 1.5}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}\n",
        name="lh.yaml",
    )
    diags = facade.validate_template(lh, format_name="sq")
    assert any(d.code == "ARC-TPL-053" for d in diags)  # still rejected, with its own message

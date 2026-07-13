"""IPEN bilingual golden case #2: renders, seeded failures, determinism (spec §8.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.diagnostics import has_errors

_REPO = Path(__file__).resolve().parents[2]
_DIR = _REPO / "examples" / "ipen-bilingual"
_TEMPLATE = _DIR / "template.yaml"
_DATA = _DIR / "data.yaml"

_TARGETS = [
    ("square", "en"), ("square", "fa"),
    ("story", "en"), ("story", "fa"),
    ("a4", "en"), ("a4", "fa"),
]


@pytest.mark.parametrize(("fmt", "locale"), _TARGETS)
def test_ipen_renders_all_targets(tmp_path: Path, fmt: str, locale: str) -> None:
    facade = build_facade()
    out = tmp_path / f"{locale}-{fmt}.png"
    result = facade.render_file(_TEMPLATE, _DATA, fmt, locale, output=out)
    assert result.ok, result.diagnostics
    assert out.is_file() and out.stat().st_size > 0
    assert not has_errors(result.diagnostics)


def test_ipen_fa_square_is_deterministic(tmp_path: Path) -> None:
    facade = build_facade()
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    r1 = facade.render_file(_TEMPLATE, _DATA, "square", "fa", output=a)
    r2 = facade.render_file(_TEMPLATE, _DATA, "square", "fa", output=b)
    assert r1.ok and r2.ok
    assert a.read_bytes() == b.read_bytes()
    assert r1.content_sha256 == r2.content_sha256


def test_ipen_debug_render_succeeds(tmp_path: Path) -> None:
    facade = build_facade()
    out = tmp_path / "debug.png"
    result = facade.render_file(_TEMPLATE, _DATA, "square", "fa", output=out, debug=True)
    assert result.ok, result.diagnostics
    assert out.stat().st_size > 0


def test_ipen_layout_inspect_json() -> None:
    report = build_facade().inspect_layout(_TEMPLATE, _DATA, "a4", "fa")
    assert report.ok
    assert report.format == "a4" and report.locale == "fa"
    assert report.canvas_px == (2480, 3508)  # A4 at 300 dpi


# ------------------------------------------------------------ seeded located failures
_HEADER = """
version: 0.1.0
formats:
  square: {canvas: {width: 300px, height: 300px, dpi: 72}}
root:
  type: group
  id: root
  children:
"""


def _validate(tmp_path: Path, body: str) -> list:
    template = tmp_path / "t.yaml"
    template.write_text(_HEADER + body, encoding="utf-8")
    return build_facade().validate_template(template, format_name="square")


def _codes(diags: list) -> set[str]:
    return {d.code for d in diags}


def test_seeded_constraint_cycle(tmp_path: Path) -> None:
    diags = _validate(
        tmp_path,
        """
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
    assert "ARC-LAY-052" in _codes(diags)
    assert all(d.source is not None for d in diags if d.code == "ARC-LAY-052")


def test_seeded_text_overflow_error(tmp_path: Path) -> None:
    diags = _validate(
        tmp_path,
        """
    - id: t
      type: text
      text: "Far too much text to fit inside this tiny fixed box at this large size"
      style: {font: Inter, font_size: 40pt, color: black}
      fit: {policy: wrap, overflow: error}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 60pt, h: 30pt}}
""",
    )
    assert "ARC-LAY-050" in _codes(diags)


def test_seeded_unknown_sibling_anchor(tmp_path: Path) -> None:
    diags = _validate(
        tmp_path,
        """
    - id: a
      type: shape
      shape: rect
      constraints: {anchor: {top: ghost.bottom, left: parent.left}, size: {w: 10pt, h: 10pt}}
""",
    )
    assert "ARC-LAY-053" in _codes(diags)


def test_seeded_missing_font(tmp_path: Path) -> None:
    diags = _validate(
        tmp_path,
        """
    - id: t
      type: text
      text: "hi"
      style: {font: NotARealFont, font_size: 20pt, color: black}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
""",
    )
    assert "ARC-RND-010" in _codes(diags)


def test_seeded_invalid_unit(tmp_path: Path) -> None:
    diags = _validate(
        tmp_path,
        """
    - id: a
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10furlongs, h: 10pt}}
""",
    )
    assert "ARC-IR-011" in _codes(diags)


def test_seeded_invalid_mask_params(tmp_path: Path) -> None:
    diags = _validate(
        tmp_path,
        """
    - id: a
      type: shape
      shape: rect
      mask: {component: diamond_grid, params: {cell: -4pt}}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
""",
    )
    assert "ARC-FX-902" in _codes(diags)


def test_seeded_missing_asset(tmp_path: Path) -> None:
    diags = _validate(
        tmp_path,
        """
    - id: pic
      type: image
      asset: nope.png
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 50pt, h: 50pt}}
""",
    )
    assert "ARC-AST-001" in _codes(diags)

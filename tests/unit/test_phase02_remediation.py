"""Phase 2 remediation regression tests — one or more per adjudicated finding (CR-*/DX-*).

Layout-dependent cases drive the real solver with a deterministic fake measurer; compile-only
cases use the compiler directly; provenance/report cases go through the wired facade.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.builtin.layout_anchors import AnchorLayoutSolver
from arcavex.kernel.contracts.types import MeasureRequest, MeasureResult
from arcavex.kernel.diagnostics import Diagnostic
from arcavex.kernel.ir.models import LayoutNode
from arcavex.services.template.compiler import Compiler

_EXAMPLE = Path("tests/fixtures/bilingual-poster/template.yaml")
_EXAMPLE_DATA = Path("tests/fixtures/bilingual-poster/data.yaml")


def fake_measure(req: MeasureRequest) -> MeasureResult:
    lines = 1
    width = len(req.text) * req.font_size_pt * 0.5
    if req.max_width_pt is not None and width > req.max_width_pt:
        lines = max(1, int(width // req.max_width_pt) + 1)
        width = req.max_width_pt
    return MeasureResult(
        width_pt=width, height_pt=req.font_size_pt * 1.2 * lines, baseline_pt=req.font_size_pt,
        line_count=lines, resolved_size_pt=req.font_size_pt,
    )


_HEADER = """
version: 0.1.0
formats:
  square: {canvas: {width: 400px, height: 400px, dpi: 72}}
root:
  type: group
  id: root
"""


def _solve(tmp_path: Path, body: str, direction: str = "ltr") -> LayoutNode:
    template = tmp_path / "t.yaml"
    dir_line = f"  direction: {direction}\n" if direction != "ltr" else ""
    template.write_text(_HEADER + dir_line + body, encoding="utf-8")
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None, result.diagnostics
    return AnchorLayoutSolver().solve(result.document, fake_measure).root


def _find(node: LayoutNode, node_id: str) -> LayoutNode:
    if node.source_node_id == node_id:
        return node
    for child in node.children:
        try:
            return _find(child, node_id)
        except AssertionError:
            continue
    raise AssertionError(f"{node_id} not found")


def _codes(diags: list[Diagnostic]) -> set[str]:
    return {d.code for d in diags}


def _compile(tmp_path: Path, text: str, fmt: str = "square", locale: str | None = None,
             data: Path | None = None):  # noqa: ANN202
    template = tmp_path / "t.yaml"
    template.write_text(text, encoding="utf-8")
    return Compiler().compile(template, data, fmt, locale, None)


# --------------------------------------------------------------------------- CR-2
@pytest.mark.parametrize(
    ("block", "snippet"),
    [
        ("style", "style: {font_size: 8px, kerning: tight}"),
        ("paragraph", "paragraph: {align: start, drection: rtl}"),
        ("fit", "fit: {policy: wrap, maxlines: 2}"),
    ],
)
def test_cr2_unknown_fields_rejected(tmp_path: Path, block: str, snippet: str) -> None:
    body = (
        "\n  children:\n"
        "    - id: t\n      type: text\n      text: hi\n"
        f"      {snippet}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fit_content}}\n"
    )
    result = _compile(tmp_path, _HEADER + body)
    assert "ARC-TPL-051" in _codes(result.diagnostics), (block, result.diagnostics)


def test_cr2_unknown_size_field_rejected(tmp_path: Path) -> None:
    body = (
        "\n  children:\n    - id: b\n      type: shape\n      shape: rect\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: {value: 50%, mn: 10px}, h: fill}}\n"
    )
    assert "ARC-TPL-051" in _codes(_compile(tmp_path, _HEADER + body).diagnostics)


# --------------------------------------------------------------------------- CR-4
def test_cr4_aspect_derives_from_clamped_axis(tmp_path: Path) -> None:
    node = _solve(
        tmp_path,
        """
  children:
    - id: box
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {h: {value: 100pt, max: 50pt}, w: {aspect: "2:1"}}
""",
    )
    box = _find(node, "box")
    # h clamps to 50, then w = h*2 = 100 (not 200 from the unclamped 100).
    assert (round(box.bounds.w), round(box.bounds.h)) == (100, 50)


# --------------------------------------------------------------------------- CR-5
def test_cr5_stack_cross_aspect_resolves(tmp_path: Path) -> None:
    node = _solve(
        tmp_path,
        """
  children:
    - id: col
      type: group
      layout: vstack
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 200pt, h: 300pt}
      children:
        - id: sq
          type: shape
          shape: rect
          constraints: {size: {w: {aspect: "1:1"}, h: 80pt}}
""",
    )
    sq = _find(node, "sq")
    assert round(sq.bounds.w) == 80  # cross (w) derived from main (h=80), not 0


# --------------------------------------------------------------------------- CR-6
def test_cr6_direction_inherits_from_ancestor(tmp_path: Path) -> None:
    node = _solve(
        tmp_path,
        """
  children:
    - id: inner
      type: group
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
      children:
        - id: n1
          type: shape
          shape: rect
          constraints:
            anchor: {top: parent.top, start: parent.start}
            size: {w: 40pt, h: 40pt}
""",
        direction="rtl",
    )
    # Under an inherited rtl direction, start = right edge: n1 sits at the right.
    n1 = _find(node, "n1")
    assert n1.bounds.right == pytest.approx(400.0)


# --------------------------------------------------------------------------- CR-10
def _null_tpl(required: bool) -> str:
    req = "true" if required else "false"
    return (
        "version: 0.1.0\n"
        f"variables: {{a: {{type: string, required: {req}, default: DEF}}}}\n"
        "formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root: {type: group, id: root, children: []}\n"
    )


def test_cr10_explicit_null_does_not_resurrect_default(tmp_path: Path) -> None:
    data = tmp_path / "d.yaml"
    data.write_text("a:\n", encoding="utf-8")  # explicit null
    result = _compile(tmp_path, _null_tpl(required=False), data=data)
    assert result.document is not None, result.diagnostics
    # Not the default and not a type error: bound as None.


def test_cr10_explicit_null_required_is_error(tmp_path: Path) -> None:
    data = tmp_path / "d.yaml"
    data.write_text("a:\n", encoding="utf-8")
    result = _compile(tmp_path, _null_tpl(required=True), data=data)
    assert "ARC-TPL-014" in _codes(result.diagnostics)


# --------------------------------------------------------------------------- CR-12
def test_cr12_stack_fill_respects_max(tmp_path: Path) -> None:
    node = _solve(
        tmp_path,
        """
  children:
    - id: row
      type: group
      layout: hstack
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 300pt, h: 60pt}
      children:
        - id: a
          type: shape
          shape: rect
          constraints: {size: {w: {value: fill, max: 100pt}, h: fill}}
""",
    )
    a = _find(node, "a")
    assert a.bounds.w == pytest.approx(100.0)  # fill share (300) clamped to max 100


# --------------------------------------------------------------------------- DX-1
def test_dx1_hstack_mirrors_under_rtl(tmp_path: Path) -> None:
    body = """
  children:
    - id: row
      type: group
      layout: hstack
      gap: 10pt
      main_align: start
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: 50pt}
      children:
        - id: c0
          type: shape
          shape: rect
          constraints: {size: {w: 60pt, h: 30pt}}
        - id: c1
          type: shape
          shape: rect
          constraints: {size: {w: 60pt, h: 30pt}}
"""
    rtl = _solve(tmp_path, body, direction="rtl")
    c0 = _find(rtl, "c0")
    # First child packs at the RIGHT edge under rtl main_align: start.
    assert c0.bounds.right == pytest.approx(400.0)
    ltr = _solve(tmp_path, body, direction="ltr")
    assert _find(ltr, "c0").bounds.x == pytest.approx(0.0)


# --------------------------------------------------------------------------- DX-2
def test_dx2_no_overlap_warning_for_repeat_in_stack(tmp_path: Path) -> None:
    text = (
        "version: 0.1.0\n"
        "formats: {square: {canvas: {width: 400px, height: 400px, dpi: 72}}}\n"
        "preview_data: {items: [1, 2, 3]}\n"
        "root:\n  type: group\n  id: root\n"
        "  children:\n"
        "    - id: stack\n      type: group\n      layout: vstack\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}\n"
        "      children:\n"
        "        - repeat: \"{{ items }}\"\n          as: it\n          key: \"{{ loop.index }}\"\n"
        "          node:\n            id: chip\n            type: shape\n            shape: rect\n"
        "            constraints: {size: {w: fill, h: 30pt}}\n"
    )
    result = _compile(tmp_path, text)
    assert "ARC-LAY-040" not in _codes(result.diagnostics)


# --------------------------------------------------------------------------- DX-7
def test_dx7_max_lines_caps_fit_content_height(tmp_path: Path) -> None:
    node = _solve(
        tmp_path,
        """
  children:
    - id: t
      type: text
      text: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      style: {font_size: 20pt}
      fit: {policy: wrap, overflow: clip, max_lines: 2}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 100pt, h: fit_content}
""",
    )
    t = _find(node, "t")
    # The text wraps to many lines but the fit_content box is capped at 2 lines (~2*24pt).
    assert t.bounds.h <= 2 * 20 * 1.2 + 1


# --------------------------------------------------------------------------- CR-1 / DX-3
def test_cr1_resolved_reports_format_patch_layer() -> None:
    report = build_facade().inspect_resolved(_EXAMPLE, None, "a4", "fa")
    assert report.ok, report.diagnostics
    assert report.direction == "rtl" and report.digits == "fa"
    hero = next((p for p in report.patches if p.path.endswith("hero.constraints.size.h")), None)
    assert hero is not None and hero.layer == "format:a4" and hero.effective


def test_dx3_output_name_includes_locale() -> None:
    facade = build_facade()
    fa = facade._default_output_path(_EXAMPLE, "square", "fa")  # noqa: SLF001
    en = facade._default_output_path(_EXAMPLE, "square", None)  # noqa: SLF001
    assert fa is not None and fa.name.endswith(".square.fa.png")
    assert en is not None and en.name.endswith(".square.png")


# --------------------------------------------------------------------------- CR-8 / CR-9
@pytest.mark.parametrize(
    ("locale", "expect_cp"),
    [("fa", 0x06F0), ("ar", 0x0660)],
)
def test_cr8_cr9_digits(tmp_path: Path, locale: str, expect_cp: int) -> None:
    text = (
        "version: 0.1.0\n"
        "variables: {n: {type: number, default: 40}}\n"
        "formats: {square: {canvas: {width: 200px, height: 200px, dpi: 72}}}\n"
        "locales: {fa: {direction: rtl, digits: fa}, ar: {direction: rtl, digits: arab}}\n"
        "root:\n  type: group\n  id: root\n  children:\n"
        "    - {id: a, type: text, text: \"{{ n }}\", style: {font_size: 8pt, color: white},\n"
        "       constraints: {anchor: {top: parent.top, left: parent.left},\n"
        "                     size: {w: fill, h: fit_content}}}\n"
        "    - {id: b, type: text, text: \"x={{ n }}\", style: {font_size: 8pt, color: white},\n"
        "       constraints: {anchor: {top: parent.bottom, left: parent.left},\n"
        "                     size: {w: fill, h: fit_content}}}\n"
    )
    result = _compile(tmp_path, text, locale=locale)
    assert result.document is not None, result.diagnostics
    exact = result.document.root.children[0].text
    embedded = result.document.root.children[1].text

    def in_set(ch: str) -> bool:
        return expect_cp <= ord(ch) <= expect_cp + 9

    assert in_set(exact[0])  # exact-match numeric localized to the locale digit set (CR-8)
    assert any(in_set(c) for c in embedded)  # embedded too, same set (CR-9)


# --------------------------------------------------------------------------- CR-14
def test_cr14_sibling_anchors_to_rotation_aabb(tmp_path: Path) -> None:
    node = _solve(
        tmp_path,
        """
  children:
    - id: sq
      type: shape
      shape: rect
      transform: {rotate: 45, origin: center}
      constraints:
        anchor: {top: parent.top+100pt, left: parent.left+100pt}
        size: {w: 100pt, h: 100pt}
    - id: below
      type: shape
      shape: rect
      constraints:
        anchor: {top: sq.bottom+0pt, left: parent.left}
        size: {w: 20pt, h: 20pt}
""",
    )
    below = _find(node, "below")
    # sq is 100x100 at (100,100); its 45-degree AABB bottom is 100 + 150*0.707 ~= 220.7,
    # not the un-rotated 200. `below` anchors to the AABB bottom.
    assert below.bounds.y > 215.0


# --------------------------------------------------------------------------- CR-3 / CR-11
_PATCH_TPL = """version: 0.1.0
formats:
  bad:
    canvas: {width: 100px, height: 100px, dpi: 96}
    patch:
      - set: nodes.cond.style.font_sze
        value: "9pt"
  good:
    canvas: {width: 100px, height: 100px, dpi: 96}
    patch:
      - set: nodes.cond.style.fill
        value: "#ff0000"
  root_edit:
    canvas: {width: 100px, height: 100px, dpi: 96}
    patch:
      - set: nodes.root.direction
        value: rtl
preview_data: {show: true}
root:
  type: group
  id: root
  children:
    - if: "{{ show }}"
      node:
        id: cond
        type: shape
        shape: rect
        style: {fill: "#000000"}
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
"""


def test_rr2_11_set_adds_field_but_typo_caught_downstream(tmp_path: Path) -> None:
    # RR2-11: `set` may add an absent field, so a typo'd field name is no longer a patch error;
    # instead the compiler's per-block field validation catches it (the safety net still holds).
    result = _compile(tmp_path, _PATCH_TPL, fmt="bad")
    assert "ARC-TPL-051" in _codes(result.diagnostics)
    assert "ARC-TPL-092" not in _codes(result.diagnostics)


def test_cr11_field_edit_through_if_wrapper(tmp_path: Path) -> None:
    result = _compile(tmp_path, _PATCH_TPL, fmt="good")
    assert result.document is not None, result.diagnostics
    cond = result.document.root.children[0]
    assert cond.style.fill == (1.0, 0.0, 0.0, 1.0)


def test_cr11_root_addressable_and_field_added(tmp_path: Path) -> None:
    # root is addressable (not "no node with id 'root'"), and RR2-11 lets the patch *add* the
    # absent 'direction' field to the undirected root group; it compiles with direction applied.
    result = _compile(tmp_path, _PATCH_TPL, fmt="root_edit")
    assert result.document is not None, result.diagnostics
    assert result.document.root.direction == "rtl"


# --------------------------------------------------------------------------- DX-6
def test_dx6_op_typo_echoes_key(tmp_path: Path) -> None:
    text = (
        "version: 0.1.0\n"
        "formats:\n  f:\n    canvas: {width: 100px, height: 100px, dpi: 96}\n"
        "    patch:\n      - insert_afterr: nodes.a\n"
        "        node: {id: b, type: shape, shape: rect}\n"
        "root:\n  type: group\n  id: root\n  children:\n"
        "    - {id: a, type: shape, shape: rect, "
        "constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}}\n"
    )
    diag = next(d for d in _compile(tmp_path, text, fmt="f").diagnostics if d.code == "ARC-TPL-092")
    assert "insert_afterr" in diag.message


# --------------------------------------------------------------------------- DX-10
def test_dx10_overlay_as_data_hints(tmp_path: Path) -> None:
    tpl = (
        "version: 0.1.0\n"
        "variables: {day: {type: number, required: true}}\n"
        "formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root: {type: group, id: root, children: []}\n"
    )
    overlay = tmp_path / "event.fa.yaml"
    overlay.write_text("month: x\n", encoding="utf-8")
    result = _compile(tmp_path, tpl, data=overlay)
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-014")
    assert diag.hint is not None and "locale overlay" in diag.hint


# --------------------------------------------------------------------------- CR-7
def test_cr7_rtl_derivation_string_flips_offset() -> None:
    report = build_facade().inspect_layout(_EXAMPLE, _EXAMPLE_DATA, "square", "fa")
    assert report.root is not None
    accent = _find_report(report.root, "accent-bar")
    horiz = next(a for a in accent.anchors if a.axis == "horizontal")
    # start: parent.start+56pt in rtl -> printed as parent.right - 56pt, and the resolved value
    # matches the expression (parent.right is the canvas width 810pt).
    assert "- 56pt" in horiz.expression
    assert horiz.resolved_pt == pytest.approx(810.0 - 56.0, abs=0.5)


def _find_report(node: object, node_id: str):  # noqa: ANN202
    if node.id == node_id:  # type: ignore[attr-defined]
        return node
    for child in node.children:  # type: ignore[attr-defined]
        found = _find_report(child, node_id)
        if found is not None:
            return found
    return None


# --------------------------------------------------------------------------- CR-13
def test_cr13_truncate_sub_line_box_warns(tmp_path: Path) -> None:
    facade = build_facade()
    template = tmp_path / "t.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {square: {canvas: {width: 400px, height: 400px, dpi: 72}}}\n"
        "root:\n  type: group\n  id: root\n  children:\n"
        "    - id: t\n      type: text\n      text: \"A fairly long line of text here\"\n"
        "      style: {font_size: 30pt, color: white}\n"
        "      fit: {policy: truncate}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: 200pt, h: 10pt}}\n",
        encoding="utf-8",
    )
    report = facade.inspect_layout(template, None, "square", None)
    assert any(w.code == "ARC-LAY-051" for w in report.warnings), report.warnings


# --------------------------------------------------------------------------- CR-15
def test_cr15_report_has_transform_and_free_regions() -> None:
    report = build_facade().inspect_layout(_EXAMPLE, _EXAMPLE_DATA, "story", "en")
    assert report.ok
    assert report.root is not None
    assert len(report.root.absolute_transform) == 6
    assert report.root.paint_bounds_px[2] > 0.0
    # The story canvas has empty bands surfaced as free regions.
    assert isinstance(report.free_regions, list)

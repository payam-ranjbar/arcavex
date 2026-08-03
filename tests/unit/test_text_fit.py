"""Text fit-policy and shaping tests (spec §4.3, ADR-0001)."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from arcavex.builtin.layout_anchors import AnchorLayoutSolver
from arcavex.kernel.contracts.types import MeasureRequest
from arcavex.kernel.diagnostics import DiagnosticError, has_errors
from arcavex.kernel.ir.models import LayoutNode, ResolvedText
from arcavex.services.template.compiler import Compiler
from arcavex.services.text import TextService

_TS = TextService()


def _measure(**kwargs: object) -> object:
    defaults: dict[str, object] = {"font_families": ("Inter",), "font_size_pt": 40.0}
    defaults.update(kwargs)
    return _TS.measure(MeasureRequest(**defaults))  # type: ignore[arg-type]


def test_shrink_to_fit_reduces_size() -> None:
    res = _measure(
        text="A rather long headline that will not fit at one size",
        font_size_pt=48.0, max_width_pt=200.0, max_height_pt=70.0,
        fit_policy="shrink_to_fit", min_size_pt=10.0,
    )
    assert res.overflow_kind == "shrunk"
    assert res.resolved_size_pt < 48.0
    assert res.height_pt <= 70.0 + 0.5


def test_shrink_to_fit_non_convergence() -> None:
    """A box too small even at min_size does not converge and reports overflowing."""
    res = _measure(
        text="Way too much text to ever fit here at all no matter what",
        font_size_pt=40.0, max_width_pt=60.0, max_height_pt=20.0,
        fit_policy="shrink_to_fit", min_size_pt=20.0,
    )
    assert res.converged is False
    assert res.overflow_kind == "overflowing"


# --------------------------------------------- ARC-LAY-051 points the right way (P1-3)
#
# The catalog used to advise "Raise min_size so a fitting size exists". 'min_size' is the *floor*
# of the shrink search, so raising it deletes the only candidates that could still fit: following
# the hint made the failure monotonically worse. These tests pin the direction behaviourally, not
# just as wording, so the advice cannot invert again without a red test.
_NON_CONVERGENT = {
    "text": "Way too much text to ever fit here at all no matter what",
    "font_size_pt": 40.0,
    "max_width_pt": 60.0,
    "max_height_pt": 60.0,
    "fit_policy": "shrink_to_fit",
}


def test_lowering_min_size_is_what_makes_the_text_fit() -> None:
    """The direction ARC-LAY-051 must recommend, measured rather than asserted."""
    too_high = _measure(**_NON_CONVERGENT, min_size_pt=20.0)
    assert too_high.converged is False

    lowered = _measure(**_NON_CONVERGENT, min_size_pt=8.0)
    assert lowered.converged is True
    assert lowered.overflow_kind == "shrunk"


def test_raising_min_size_is_monotonically_worse() -> None:
    """Every step up the floor makes the overflow larger — never smaller."""
    heights = [
        _measure(**_NON_CONVERGENT, min_size_pt=floor).height_pt for floor in (12.0, 20.0, 30.0)
    ]
    assert heights == sorted(heights), heights
    assert all(h > _NON_CONVERGENT["max_height_pt"] for h in heights)


def test_lay051_hint_recommends_lowering_min_size() -> None:
    """Both the catalog entry and the solver's raise-site hint must say lower, not raise."""
    from arcavex.services.diagnostics_catalog import CATALOG

    fix = CATALOG["ARC-LAY-051"].fix
    assert "Lower min_size" in fix
    assert "Raise min_size" not in fix


def test_truncate_appends_ellipsis() -> None:
    res = _measure(
        text="This is a long line that should be truncated with an ellipsis",
        font_size_pt=30.0, max_width_pt=200.0, max_height_pt=45.0, fit_policy="truncate",
    )
    assert res.overflow_kind == "truncated"
    assert res.out_text is not None and res.out_text.endswith("…")
    assert len(res.out_text) < 62


def test_missing_glyph_detected() -> None:
    # An emoji is in no bundled font, so it is flagged; Latin/Farsi are not.
    res = _measure(text="hi \U0001F600", font_families=("Inter",))
    cps = [cp for cp, _ in res.missing_glyphs]
    assert 0x1F600 in cps
    assert ord("h") not in cps


def test_nfc_normalization() -> None:
    # A decomposed sequence (e + combining acute) normalizes to one code point for shaping;
    # both forms measure to the same width.
    composed = _measure(text=unicodedata.normalize("NFC", "é"), font_size_pt=40.0)
    decomposed = _measure(text="é", font_size_pt=40.0)
    assert abs(composed.width_pt - decomposed.width_pt) < 0.01


def test_rtl_farsi_measures() -> None:
    res = _measure(text="سلام دنیا", font_families=("Vazirmatn",), direction="rtl")
    assert res.width_pt > 0 and res.height_pt > 0


# ------------------------------------------------------------ solver-level fit policies
_HEADER = """
version: 0.1.0
formats:
  square: {canvas: {width: 400px, height: 400px, dpi: 72}}
root:
  type: group
  id: root
  children:
"""


def _solve(tmp_path: Path, body: str):  # noqa: ANN202
    template = tmp_path / "t.yaml"
    template.write_text(_HEADER + body, encoding="utf-8")
    result = Compiler(available_fonts=frozenset(_TS.families)).compile(
        template, None, "square", None, None
    )
    assert result.document is not None, result.diagnostics
    return AnchorLayoutSolver().solve(result.document, _TS.measure)


def _find(node: LayoutNode, node_id: str) -> LayoutNode:
    if node.source_node_id == node_id:
        return node
    for child in node.children:
        try:
            return _find(child, node_id)
        except AssertionError:
            continue
    raise AssertionError(f"{node_id} not found")


def test_overflow_error_raises_lay050(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError) as exc:
        _solve(
            tmp_path,
            """
    - id: t
      type: text
      text: "This is far too much text to fit in a tiny fixed box at this size"
      style: {font: Inter, font_size: 40pt, color: black}
      fit: {policy: wrap, overflow: error}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 80pt, h: 40pt}
""",
        )
    assert exc.value.diagnostics[0].code == "ARC-LAY-050"


# ------------------------------------------------- max_lines at the shrink floor (ARC-LAY-057)
#
# A footer that shrank to its min_size floor and *still* needs two lines used to be reported as
# ARC-LAY-050 "overflows its box (WxH into WxH)", which points at the box height. Enlarging the
# height cannot fix a max_lines violation — the measured height is just what those lines occupy,
# so the same number comes back — and a real author lost a debugging cycle to it. The line cap
# is the binding constraint and gets its own code. The box below is deliberately given far more
# height than the text needs (60pt for an 18pt block), so the test fails if the code ever goes
# back to blaming box geometry.
_FLOOR_MAX_LINES = """
    - id: footer-venue-2
      type: text
      text: "The Hollow Chapel at Marrow Lane, Old Town Quarter, Saturday the fourteenth"
      style: {font: Inter, font_size: 16pt, color: black}
      fit: {policy: shrink_to_fit, min_size: 7.5pt, max_lines: 1, overflow: %s}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 187.5pt, h: 60pt}
"""


def test_max_lines_at_shrink_floor_raises_lay057_not_lay050(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError) as exc:
        _solve(tmp_path, _FLOOR_MAX_LINES % "error")
    diag = exc.value.diagnostics[0]
    assert diag.code == "ARC-LAY-057"
    assert diag.code != "ARC-LAY-050"


def test_lay057_message_reports_lines_cap_and_floor(tmp_path: Path) -> None:
    """The message must carry the line count, the cap, and the floor — not a WxH pair."""
    with pytest.raises(DiagnosticError) as exc:
        _solve(tmp_path, _FLOOR_MAX_LINES % "error")
    diag = exc.value.diagnostics[0]
    assert "2 lines" in diag.message  # measured line count at the floor
    assert "'max_lines' is 1" in diag.message  # the cap it violates
    assert "7.5pt shrink floor" in diag.message  # the floor it reached
    # The height pair is exactly what misled the original author; it must not reappear.
    assert "60.0pt" not in diag.message
    assert diag.hint is not None
    assert "Enlarging the box height will not help" in diag.hint


def test_lay057_hint_is_actionable_widening_the_box_fixes_it(tmp_path: Path) -> None:
    """The hint leads 'widen the box', so widening must actually resolve the error."""
    layout = _solve(tmp_path, _FLOOR_MAX_LINES.replace("w: 187.5pt", "w: 340pt") % "error")
    node = _find(layout.root, "footer-venue-2")
    assert node.overflow.kind != "overflowing"


@pytest.mark.parametrize("overflow", ["clip", "allow"])
def test_max_lines_at_floor_keeps_non_error_policies_soft(tmp_path: Path, overflow: str) -> None:
    """clip/allow must not become a hard error just because max_lines is the cause."""
    layout = _solve(tmp_path, _FLOOR_MAX_LINES % overflow)
    node = _find(layout.root, "footer-venue-2")
    assert node.overflow.kind == ("clipped" if overflow == "clip" else "overflowing")
    # Non-convergence at the floor is still only the ARC-LAY-051 warning, and the render lives.
    assert any(w.code == "ARC-LAY-051" for w in layout.warnings)
    assert not has_errors(list(layout.warnings))


def test_truncate_with_max_lines_does_not_error(tmp_path: Path) -> None:
    """'truncate' trims to fit rather than overflowing, so no ARC-LAY-050/057 is raised."""
    layout = _solve(
        tmp_path,
        _FLOOR_MAX_LINES.replace("policy: shrink_to_fit, min_size: 7.5pt, ", "policy: truncate, ")
        % "error",
    )
    node = _find(layout.root, "footer-venue-2")
    assert isinstance(node.resolved_content, ResolvedText)
    assert node.resolved_content.text.endswith("…")


def test_genuine_box_overflow_still_raises_lay050(tmp_path: Path) -> None:
    """No max_lines in play: the box really is too small, so ARC-LAY-050 is the honest code."""
    with pytest.raises(DiagnosticError) as exc:
        _solve(
            tmp_path,
            """
    - id: t
      type: text
      text: "Way too much text to ever fit here at all no matter what"
      style: {font: Inter, font_size: 40pt, color: black}
      fit: {policy: shrink_to_fit, min_size: 20pt, overflow: error}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 60pt, h: 20pt}
""",
        )
    assert exc.value.diagnostics[0].code == "ARC-LAY-050"


# ------------------------------------------- max_lines under 'wrap' (P1-4, also ARC-LAY-057)
#
# 'wrap' does no shrink search, so there is no floor to bottom out at — but the line cap binds
# exactly the same way, and the reported height is just as inert. Measured on this node, the
# error quoted the identical 76.0pt measured height at box heights of 60, 80, 200 and 400pt.
_WRAP_MAX_LINES = """
    - id: footer-venue-2
      type: text
      text: "The Hollow Chapel at Marrow Lane, Old Town Quarter, Saturday the fourteenth"
      style: {font: Inter, font_size: 16pt, color: black}
      fit: {policy: wrap, max_lines: 1, overflow: error}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 187.5pt, h: %s}
"""


def test_wrap_max_lines_raises_lay057_not_lay050(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError) as exc:
        _solve(tmp_path, _WRAP_MAX_LINES % "60pt")
    assert exc.value.diagnostics[0].code == "ARC-LAY-057"


def test_wrap_lay057_names_the_authored_size_not_a_shrink_floor(tmp_path: Path) -> None:
    """Under 'wrap' there is no floor, so the message must not invent one."""
    with pytest.raises(DiagnosticError) as exc:
        _solve(tmp_path, _WRAP_MAX_LINES % "60pt")
    diag = exc.value.diagnostics[0]
    assert "4 lines" in diag.message
    assert "'max_lines' is 1" in diag.message
    assert "16.0pt" in diag.message
    assert "shrink floor" not in diag.message
    assert diag.hint is not None
    # No min_size exists to lower, so the hint must not tell the author to lower one.
    assert "min_size" not in diag.hint.split("switch to")[0]
    assert "Enlarging the box height will not help" in diag.hint


@pytest.mark.parametrize("box_height", ["60pt", "80pt", "200pt", "400pt"])
def test_wrap_max_lines_error_survives_any_box_height(tmp_path: Path, box_height: str) -> None:
    """The proof that the old height pair was inert: growing the box never resolves the cap."""
    with pytest.raises(DiagnosticError) as exc:
        _solve(tmp_path, _WRAP_MAX_LINES % box_height)
    assert exc.value.diagnostics[0].code == "ARC-LAY-057"


def test_wrap_without_max_lines_still_raises_lay050(tmp_path: Path) -> None:
    """No cap in play under 'wrap' means the box really is the problem."""
    with pytest.raises(DiagnosticError) as exc:
        _solve(tmp_path, _WRAP_MAX_LINES.replace(", max_lines: 1", "") % "60pt")
    assert exc.value.diagnostics[0].code == "ARC-LAY-050"


def test_wrap_max_lines_too_narrow_for_a_line_still_raises_lay050(tmp_path: Path) -> None:
    """Width genuinely does not fit, so box geometry is the honest report even with a cap."""
    with pytest.raises(DiagnosticError) as exc:
        _solve(
            tmp_path,
            """
    - id: t
      type: text
      text: "MMMMMMMM"
      style: {font: Inter, font_size: 40pt, color: black}
      fit: {policy: wrap, max_lines: 1, overflow: error}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 4pt, h: 300pt}
""",
        )
    assert exc.value.diagnostics[0].code == "ARC-LAY-050"


@pytest.mark.parametrize("overflow", ["clip", "allow"])
def test_wrap_max_lines_keeps_non_error_policies_soft(tmp_path: Path, overflow: str) -> None:
    body = (_WRAP_MAX_LINES % "60pt").replace("overflow: error", f"overflow: {overflow}")
    layout = _solve(tmp_path, body)
    node = _find(layout.root, "footer-venue-2")
    assert node.overflow.kind == ("clipped" if overflow == "clip" else "overflowing")
    assert not has_errors(list(layout.warnings))


def test_lay051_solver_hint_recommends_lowering_min_size(tmp_path: Path) -> None:
    """The warning an author actually reads at the raise site, not just the catalog page."""
    layout = _solve(
        tmp_path,
        """
    - id: t
      type: text
      text: "Way too much text to ever fit here at all no matter what"
      style: {font: Inter, font_size: 40pt, color: black}
      fit: {policy: shrink_to_fit, min_size: 20pt, overflow: allow}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 60pt, h: 60pt}
""",
    )
    warning = next(w for w in layout.warnings if w.code == "ARC-LAY-051")
    assert warning.hint is not None
    assert "Lower min_size" in warning.hint
    assert "Raise min_size" not in warning.hint


def test_box_too_narrow_for_one_glyph_still_raises_lay050(tmp_path: Path) -> None:
    """max_lines is violated too, but no line fits the width — that is real box geometry.

    Widening is the only fix and ARC-LAY-050's measured-vs-box width pair shows exactly why,
    so the line-cap code must not swallow this case.
    """
    with pytest.raises(DiagnosticError) as exc:
        _solve(
            tmp_path,
            """
    - id: t
      type: text
      text: "MMMMMMMM"
      style: {font: Inter, font_size: 40pt, color: black}
      fit: {policy: shrink_to_fit, min_size: 20pt, max_lines: 1, overflow: error}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 4pt, h: 300pt}
""",
        )
    assert exc.value.diagnostics[0].code == "ARC-LAY-050"


def test_overflow_clip_records_state(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
    - id: t
      type: text
      text: "This is far too much text to fit in a tiny fixed box at this size"
      style: {font: Inter, font_size: 40pt, color: black}
      fit: {policy: wrap, overflow: clip}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 80pt, h: 40pt}
""",
    )
    node = _find(layout.root, "t")
    assert node.overflow.kind == "clipped"
    assert isinstance(node.resolved_content, ResolvedText)
    assert node.resolved_content.clip is True


def test_auto_direction_resolves_farsi_to_rtl(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
    - id: t
      type: text
      text: "سلام دنیا"
      style: {font: Vazirmatn, font_size: 30pt, color: black}
      paragraph: {align: start, direction: auto}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
""",
    )
    node = _find(layout.root, "t")
    assert isinstance(node.resolved_content, ResolvedText)
    assert node.resolved_content.direction == "rtl"


def test_missing_glyph_warns_in_layout(tmp_path: Path) -> None:
    layout = _solve(
        tmp_path,
        """
    - id: t
      type: text
      text: "hi \U0001F600"
      style: {font: Inter, font_size: 30pt, color: black}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
""",
    )
    assert any(w.code == "ARC-RND-011" for w in layout.warnings)
    assert not has_errors(list(layout.warnings))  # it is a warning, not an error

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

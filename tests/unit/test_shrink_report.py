"""A ``shrink_to_fit`` result is flagged ``shrunk`` only when the size visibly moved (BX-42).

The fit search always lands a little under the base size once the base overflowed at all, so the
old "any shrink" flag fired for a fifth of a point — and the report showed only the box extents,
so a 0.13% width delta read as a shrink event while an 11% shrink looked the same. A shrink is now
flagged only when it moved the size by at least the larger of 1pt and 2% of the base, and the
report carries ``base_size_pt`` and ``resolved_size_pt`` so the loss is read from the sizes. The
resolved size is exact either way, so nothing is hidden from a reader of the raw number.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import LayoutReport
from arcavex.kernel.contracts.types import MeasureRequest, MeasureResult
from arcavex.services.text import TextService

_TS = TextService()


# ------------------------------------------------------------------- text service outcome
def _measure(**kwargs: object) -> MeasureResult:
    defaults: dict[str, object] = {"font_families": ("Inter",), "font_size_pt": 40.0}
    defaults.update(kwargs)
    return _TS.measure(MeasureRequest(**defaults))  # type: ignore[arg-type]


def _natural_width(text: str, size: float) -> float:
    return _measure(text=text, font_size_pt=size).width_pt


def test_half_percent_shrink_is_not_flagged() -> None:
    width = _natural_width("Golden Crust", 100.0)
    res = _measure(
        text="Golden Crust", font_size_pt=100.0, max_width_pt=width * 0.995,
        fit_policy="shrink_to_fit", max_lines=1, min_size_pt=50.0,
    )
    assert res.overflow_kind == "none"
    assert 99.0 < res.resolved_size_pt < 100.0


def test_eight_percent_shrink_is_flagged_with_the_resolved_size() -> None:
    width = _natural_width("Golden Crust", 100.0)
    res = _measure(
        text="Golden Crust", font_size_pt=100.0, max_width_pt=width * 0.92,
        fit_policy="shrink_to_fit", max_lines=1, min_size_pt=50.0,
    )
    assert res.overflow_kind == "shrunk"
    assert res.resolved_size_pt == pytest.approx(92.0, abs=0.8)


def test_the_two_percent_rule_scales_with_the_size() -> None:
    """At 400pt a 1.5% shrink is 6pt — well past the 1pt floor — and still below notice."""
    width = _natural_width("Golden Crust", 400.0)
    res = _measure(
        text="Golden Crust", font_size_pt=400.0, max_width_pt=width * 0.985,
        fit_policy="shrink_to_fit", max_lines=1, min_size_pt=200.0,
    )
    assert res.overflow_kind == "none"
    assert 393.0 < res.resolved_size_pt < 400.0


# ------------------------------------------------------------------------ layout report
# 400x400px at 72dpi, so 1px == 1pt.
_HEAD = (
    "version: 0.1.0\n"
    "formats: {sq: {canvas: {width: 400px, height: 400px, dpi: 72}}}\n"
    "root:\n  type: group\n  id: root\n  children:\n"
)


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201
    return build_facade()


def _inspect(facade, tmp_path: Path, body: str) -> LayoutReport:  # noqa: ANN001
    template = tmp_path / "t.yaml"
    template.write_text(_HEAD + body, encoding="utf-8")
    report = facade.inspect_layout(template, format_name="sq")
    assert report.ok, [d.code for d in report.diagnostics]
    return report


def _headline(text: str, size: str, width: str) -> str:
    return (
        f"    - id: headline\n      type: text\n      text: {text}\n"
        f"      style: {{font: Inter, font_size: {size}, color: '#000000'}}\n"
        "      fit: {policy: shrink_to_fit, min_size: 10pt, max_lines: 1}\n"
        "      constraints: {anchor: {top: parent.top+20pt, left: parent.left+20pt}, "
        f"size: {{w: {width}, h: fit_content}}}}\n"
    )


def test_shrunk_text_reports_the_sizes_it_moved_between(facade, tmp_path) -> None:  # noqa: ANN001
    """A real shrink carries both sizes, so the author judges the loss rather than a box delta."""
    report = _inspect(
        facade, tmp_path, _headline("A headline that must shrink hard", "48pt", "300pt")
    )
    assert report.root is not None
    (node,) = report.root.children
    assert node.overflow is not None and node.overflow.kind == "shrunk"
    assert node.overflow.base_size_pt == 48.0
    assert node.overflow.resolved_size_pt is not None
    assert node.overflow.resolved_size_pt < 48.0 * 0.92


def test_sub_threshold_shrink_is_not_flagged_in_the_report(facade, tmp_path) -> None:  # noqa: ANN001
    """A box 0.5% too narrow shrinks the size by under a point: reported, but not flagged.

    The search lands where the text stops wrapping, which hinting moves off the linear estimate
    by a few tenths of a point, so the size is only pinned to the sub-point band.
    """
    natural = _inspect(facade, tmp_path, _headline("Golden Crust", "40pt", "fit_content"))
    assert natural.root is not None and natural.root.children[0].overflow is not None
    width = natural.root.children[0].overflow.measured_w_pt
    tight = _inspect(
        facade, tmp_path, _headline("Golden Crust", "40pt", f"{width * 0.995:.2f}pt")
    )
    assert tight.root is not None
    (node,) = tight.root.children
    assert node.overflow is not None and node.overflow.kind == "none"
    assert node.overflow.base_size_pt == 40.0
    assert node.overflow.resolved_size_pt is not None
    assert 39.0 < node.overflow.resolved_size_pt < 40.0

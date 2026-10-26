"""Font metrics through the single shaper (spec §4.3): units, fallback, and layout parity.

``font metrics`` exists so a box can be sized from the engine's own measurements — a line
height, a cap height, a sample's advance — instead of PIL/fontTools and synthetic templates.
These pin the two properties that make it trustworthy: the size grammar (pt exact, px at a
stated dpi, a bare number is pixels as in a template) and that the reported line height is
exactly what the shaper gives a one-line text node, so a ``fit_content`` box is not one wrap
short.
"""

from __future__ import annotations

import pytest

from arcavex.kernel.contracts.types import FontMetricsRequest, MeasureRequest
from arcavex.services.text import TextService

_TS = TextService()


def test_font_metrics_inter_at_40pt_are_positive() -> None:
    report = _TS.font_metrics(FontMetricsRequest(family="Inter", size="40pt"))
    assert report.ok and report.fallback is False
    assert report.resolved_family == "Inter"
    assert report.size_pt == pytest.approx(40.0)
    assert report.size_px == pytest.approx(40.0 * 96 / 72)
    for value in (
        report.ascent_pt,
        report.descent_pt,
        report.line_height_pt,
        report.cap_height_pt,
        report.x_height_pt,
        report.advance_pt,
    ):
        assert value > 0


def test_font_metrics_line_height_matches_a_one_line_text_node() -> None:
    """The reported line height IS the shaper's height for the same one-line text."""
    sample = "Hamburgefonstiv"
    report = _TS.font_metrics(FontMetricsRequest(family="Inter", size="40pt", sample=sample))
    node = _TS.measure(
        MeasureRequest(text=sample, font_families=("Inter",), font_size_pt=40.0)
    )
    assert report.line_height_pt == pytest.approx(node.height_pt, abs=1e-6)
    assert report.advance_pt == pytest.approx(node.width_pt, abs=1e-6)


def test_font_metrics_px_resolves_against_dpi() -> None:
    report = _TS.font_metrics(FontMetricsRequest(family="Inter", size="54px", dpi=96))
    assert report.size_pt == pytest.approx(40.5)  # 54 * 72 / 96
    assert report.size_px == pytest.approx(54.0)
    assert report.dpi == 96


def test_font_metrics_bare_number_is_pixels_like_a_template() -> None:
    """A bare size reads like a template's 'font_size': pixels at the stated dpi."""
    report = _TS.font_metrics(FontMetricsRequest(family="Inter", size="40", dpi=96))
    assert report.size_px == pytest.approx(40.0)
    assert report.size_pt == pytest.approx(30.0)  # 40 * 72 / 96


def test_font_metrics_unknown_family_falls_back_but_errors() -> None:
    """A name that is not in the database is an error; the fallback face is still reported."""
    report = _TS.font_metrics(FontMetricsRequest(family="Nonesuch", size="40pt"))
    assert report.ok is False
    assert report.fallback is True and report.resolved_family == "Inter"
    assert report.diagnostics[0].code == "ARC-RND-010"
    assert report.diagnostics[0].severity == "error"


def test_font_metrics_rejects_an_unparseable_size() -> None:
    report = _TS.font_metrics(FontMetricsRequest(family="Inter", size="huge"))
    assert report.ok is False and report.diagnostics[0].code == "ARC-IR-011"


def test_font_metrics_rejects_a_non_positive_dpi() -> None:
    report = _TS.font_metrics(FontMetricsRequest(family="Inter", size="40pt", dpi=0))
    assert report.ok is False and report.diagnostics[0].code == "ARC-IR-013"


def test_font_metrics_rejects_a_multi_line_sample() -> None:
    report = _TS.font_metrics(FontMetricsRequest(family="Inter", size="40pt", sample="a\nb"))
    assert report.ok is False and report.diagnostics[0].code == "ARC-IR-011"

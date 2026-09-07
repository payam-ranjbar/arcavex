"""Sibling-overlap classification: content collision vs. effect spill.

``paint_bounds`` is inflated so the renderer can allocate room for a shadow or a tear. Using it
as the sole basis for collision reporting made every shadowed node look like a bug, which buried
the one real collision among a dozen false ones. ``SiblingOverlap.kind`` separates them:
``content`` when the layout bounds themselves intersect, ``halo`` when only the grown boxes do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import LayoutReport

# 400x400px at 72dpi, so 1px == 1pt and every number below is directly checkable.
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


def _kinds(report: LayoutReport) -> dict[frozenset[str], str]:
    return {frozenset((ov.a, ov.b)): ov.kind for ov in report.overlaps}


def _text(node_id: str, anchor: str, extra: str = "") -> str:
    return (
        f"    - id: {node_id}\n      type: text\n      text: Overlapping line\n"
        "      style: {font: Inter, font_size: 14pt, color: '#000000'}\n"
        f"{extra}"
        f"      constraints: {{anchor: {{{anchor}}}, size: {{w: 200pt, h: 40pt}}}}\n"
    )


def _rect(node_id: str, anchor: str, size: str = "{w: 100pt, h: 40pt}", extra: str = "") -> str:
    return (
        f"    - id: {node_id}\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#3366cc'}\n"
        f"{extra}"
        f"      constraints: {{anchor: {{{anchor}}}, size: {size}}}\n"
    )


# --------------------------------------------------------------------------- content
def test_adjacent_text_boxes_overlapping_by_4pt_is_one_content_overlap(facade, tmp_path) -> None:  # noqa: ANN001
    """The genuine case: two text boxes whose layout boxes bite into each other by 4pt."""
    report = _inspect(
        facade,
        tmp_path,
        _text("venue-1", "top: parent.top+100pt, left: parent.left+20pt")
        + _text("venue-2", "top: venue-1.bottom-4pt, left: parent.left+20pt"),
    )
    assert _kinds(report) == {frozenset(("venue-1", "venue-2")): "content"}
    # The reported rect is the collision itself, so its height *is* the depth to fix.
    (ov,) = report.overlaps
    assert ov.rect_pt[3] == pytest.approx(4.0, abs=0.05)


def test_clearing_text_boxes_report_no_overlap_at_all(facade, tmp_path) -> None:  # noqa: ANN001
    """The control for the case above: a 4pt gap instead of a 4pt bite reports nothing."""
    report = _inspect(
        facade,
        tmp_path,
        _text("venue-1", "top: parent.top+100pt, left: parent.left+20pt")
        + _text("venue-2", "top: venue-1.bottom+4pt, left: parent.left+20pt"),
    )
    assert report.overlaps == []


# ------------------------------------------------------------------------------ halo
def _shadow(blur_pt: float) -> str:
    """A centred drop-shadow block; its bounds grow by 3 sigma, i.e. ``3 * blur_pt``."""
    return (
        "      effects:\n"
        "        - {name: drop-shadow, params: "
        f"{{dx: 0pt, dy: 0pt, blur: {blur_pt:g}pt, color: '#000000'}}}}\n"
    )


_SHADOW = _shadow(20)  # reaches 60pt on every side


def test_drop_shadowed_strip_beside_clean_neighbour_is_halo_only(facade, tmp_path) -> None:  # noqa: ANN001
    """A 20pt blur reaches 60pt (3 sigma) past the box; the neighbour sits 10pt away.

    The boxes themselves clear by 10pt, so this is spill, not a collision.
    """
    report = _inspect(
        facade,
        tmp_path,
        _rect("strip", "top: parent.top+100pt, left: parent.left+20pt", extra=_SHADOW)
        + _rect("neighbour", "top: parent.top+100pt, left: strip.right+10pt"),
    )
    assert _kinds(report) == {frozenset(("strip", "neighbour")): "halo"}
    assert [ov for ov in report.overlaps if ov.kind == "content"] == []


def test_torn_paper_amplitude_brushing_a_neighbour_is_halo(facade, tmp_path) -> None:  # noqa: ANN001
    """Torn-paper pushes out by its amplitude (12pt) across a 6pt gap — spill, not collision."""
    torn = (
        "      effects:\n"
        "        - {name: torn-paper, params: {amplitude: 12pt, segment: 20pt}}\n"
    )
    report = _inspect(
        facade,
        tmp_path,
        _rect("tag", "top: parent.top+100pt, left: parent.left+20pt", extra=torn)
        + _rect("caption", "top: parent.top+100pt, left: tag.right+6pt"),
    )
    assert _kinds(report) == {frozenset(("tag", "caption")): "halo"}


def test_shadow_reaching_past_a_neighbour_that_also_collides_is_content(facade, tmp_path) -> None:  # noqa: ANN001
    """Content wins over halo: a shadowed node that *also* really collides is not downgraded."""
    report = _inspect(
        facade,
        tmp_path,
        _rect("strip", "top: parent.top+100pt, left: parent.left+20pt", extra=_SHADOW)
        + _rect("neighbour", "top: parent.top+100pt, left: strip.right-10pt"),
    )
    assert _kinds(report) == {frozenset(("strip", "neighbour")): "content"}
    # ...and the rect is the 10pt bite, not the 60pt shadow reach.
    (ov,) = report.overlaps
    assert ov.rect_pt[2] == pytest.approx(10.0, abs=0.05)


def test_one_content_overlap_survives_a_crowd_of_halos(facade, tmp_path) -> None:  # noqa: ANN001
    """The whole point: the real collision stays findable next to several shadow halos.

    Three shadowed strips spill over their neighbours; one pair genuinely collides. Before the
    ``kind`` split, all four read identically and the real one had to be found by eye.

    The rows are 80pt apart and the blur reaches 18pt, so each strip spills only sideways onto
    its own tag — the isolation the assertion below depends on.
    """
    body = "".join(
        _rect(f"strip-{i}", f"top: parent.top+{20 + i * 80}pt, left: parent.left+20pt",
              extra=_shadow(6))
        + _rect(f"tag-{i}", f"top: parent.top+{20 + i * 80}pt, left: strip-{i}.right+10pt")
        for i in range(3)
    )
    body += (
        _text("footer-venue-1", "top: parent.top+300pt, left: parent.left+20pt")
        + _text("footer-venue-2", "top: footer-venue-1.bottom-4pt, left: parent.left+20pt")
    )
    report = _inspect(facade, tmp_path, body)
    content = [ov for ov in report.overlaps if ov.kind == "content"]
    halo = [ov for ov in report.overlaps if ov.kind == "halo"]
    assert [frozenset((ov.a, ov.b)) for ov in content] == [
        frozenset(("footer-venue-1", "footer-venue-2"))
    ]
    assert len(halo) == 3


# ------------------------------------------------------------------- backdrop interaction
def test_full_bleed_backdrop_stays_suppressed_and_its_shadow_grants_no_immunity(
    facade, tmp_path  # noqa: ANN001
) -> None:
    """DX-8 suppression still applies to a real backdrop, and only to a real backdrop.

    ``_is_backdrop`` reads the content box, so a heavily shadowed but small node cannot inflate
    its way past the 90%-of-region threshold and have its containment silently dropped. The
    shadowed panel is painted *over* the node it covers, so it is a lid hiding a sibling rather
    than a plate beneath one (see test_layout_structure.py for that distinction).
    """
    report = _inspect(
        facade,
        tmp_path,
        _rect("bg", "top: parent.top, left: parent.left", size="{w: 100%, h: 100%}")
        + _rect("swallowed", "top: parent.top+60pt, left: parent.left+60pt",
                size="{w: 40pt, h: 40pt}")
        + _rect("panel", "top: parent.top+40pt, left: parent.left+40pt",
                size="{w: 200pt, h: 200pt}", extra=_SHADOW),
    )
    kinds = _kinds(report)
    # The genuine full-bleed backdrop enclosing both is still noise.
    assert frozenset(("bg", "panel")) not in kinds
    assert frozenset(("bg", "swallowed")) not in kinds
    # The shadowed panel painted over a sibling it covers hides it: a real bug, still content.
    assert kinds[frozenset(("panel", "swallowed"))] == "content"

"""Sibling overlaps that are structure, grazes, or text ink — not collisions (BX-42).

On a two-format poster an assistant authored, ``layout inspect`` listed twelve ``content``
overlaps that were all by design — a stroke-only frame around the content it framed, text lines
whose empty leading touched a neighbour's box, rules sitting inside a headline's line box — and
the one real collision was one line among them. These tests pin what now separates the design
from the mistake:

- a stroke-only frame (no fill, or a transparent one) that fully contains a sibling is structure;
  one that only partially overlaps runs its outline through the neighbour and stays ``content``;
- a filled plate painted *beneath* a sibling it fully contains is a card, not a collision; the same
  shape painted *over* the sibling hides it and stays ``content``;
- an intersection no deeper than 1pt, or under 2% of the smaller box, is a ``touch``;
- a text node's collision box is narrowed to its shaped width along the paragraph alignment, so a
  short centred word does not collide with what sits under the empty ends of its box.

The companion change — a ``shrink_to_fit`` outcome flagged only when the size visibly moved — is
pinned in test_shrink_report.py.
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


def _text(node_id: str, anchor: str) -> str:
    return (
        f"    - id: {node_id}\n      type: text\n      text: Overlapping line\n"
        "      style: {font: Inter, font_size: 14pt, color: '#000000'}\n"
        f"      constraints: {{anchor: {{{anchor}}}, size: {{w: 200pt, h: 40pt}}}}\n"
    )


def _rect(node_id: str, anchor: str, size: str = "{w: 100pt, h: 40pt}", extra: str = "") -> str:
    return (
        f"    - id: {node_id}\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#3366cc'}\n"
        f"{extra}"
        f"      constraints: {{anchor: {{{anchor}}}, size: {size}}}\n"
    )


def _frame(node_id: str, anchor: str, size: str, fill: str | None = "'#00000000'") -> str:
    """A stroke-only rounded frame: the outline is its only ink, so its fill is transparent."""
    fill_field = f"fill: {fill}, " if fill is not None else ""
    return (
        f"    - id: {node_id}\n      type: shape\n      shape: rrect\n"
        f"      style: {{{fill_field}stroke: '#4b2a14', stroke_width: 2pt, corner_radius: 8pt}}\n"
        f"      constraints: {{anchor: {{{anchor}}}, size: {size}}}\n"
    )


# ------------------------------------------------------------------------------ frames
@pytest.mark.parametrize("fill", ["'#00000000'", None], ids=["alpha-zero", "no-fill"])
def test_stroke_only_frame_around_its_content_is_structure(facade, tmp_path, fill) -> None:  # noqa: ANN001
    """A frame drawn *around* a label and a swatch is the design, not two collisions."""
    report = _inspect(
        facade,
        tmp_path,
        _frame("frame", "top: parent.top+20pt, left: parent.left+20pt",
               "{w: 300pt, h: 150pt}", fill=fill)
        + _text("label", "top: parent.top+50pt, left: parent.left+40pt")
        + _rect("swatch", "top: parent.top+110pt, left: parent.left+40pt"),
    )
    assert report.overlaps == []


def test_stroke_only_frame_crossing_a_neighbour_is_content(facade, tmp_path) -> None:  # noqa: ANN001
    """Partial overlap means the outline itself runs through the neighbour: a real collision."""
    report = _inspect(
        facade,
        tmp_path,
        _frame("frame", "top: parent.top+20pt, left: parent.left+20pt", "{w: 200pt, h: 100pt}")
        + _rect("swatch", "top: parent.top+60pt, left: parent.left+150pt"),
    )
    assert _kinds(report) == {frozenset(("frame", "swatch")): "content"}
    (ov,) = report.overlaps
    assert ov.rect_pt[2] == pytest.approx(70.0, abs=0.05)


# ------------------------------------------------------------------------------ plates
def test_filled_plate_beneath_the_label_it_contains_is_structure(facade, tmp_path) -> None:  # noqa: ANN001
    """A card: a filled panel painted first, with a label and a swatch fully inside it."""
    report = _inspect(
        facade,
        tmp_path,
        _rect("plate", "top: parent.top+40pt, left: parent.left+40pt",
              size="{w: 240pt, h: 120pt}")
        + _text("label", "top: parent.top+60pt, left: parent.left+60pt")
        + _rect("swatch", "top: parent.top+110pt, left: parent.left+60pt",
                size="{w: 60pt, h: 30pt}"),
    )
    assert report.overlaps == []


def test_plate_lowered_beneath_its_label_by_z_is_structure(facade, tmp_path) -> None:  # noqa: ANN001
    """Paint order, not declaration order, decides which node is underneath."""
    report = _inspect(
        facade,
        tmp_path,
        _text("label", "top: parent.top+60pt, left: parent.left+60pt")
        + _rect("plate", "top: parent.top+40pt, left: parent.left+40pt",
                size="{w: 240pt, h: 120pt}", extra="      z: -1\n"),
    )
    assert report.overlaps == []


def test_filled_shape_painted_over_a_sibling_it_covers_is_content(facade, tmp_path) -> None:  # noqa: ANN001
    """The same geometry with the paint order flipped hides the label: a genuine bug."""
    report = _inspect(
        facade,
        tmp_path,
        _text("label", "top: parent.top+60pt, left: parent.left+60pt")
        + _rect("lid", "top: parent.top+40pt, left: parent.left+40pt",
                size="{w: 240pt, h: 120pt}"),
    )
    assert _kinds(report) == {frozenset(("label", "lid")): "content"}


def test_two_filled_shapes_that_merely_intersect_stay_content(facade, tmp_path) -> None:  # noqa: ANN001
    report = _inspect(
        facade,
        tmp_path,
        _rect("a", "top: parent.top+40pt, left: parent.left+40pt")
        + _rect("b", "top: parent.top+60pt, left: parent.left+90pt"),
    )
    assert _kinds(report) == {frozenset(("a", "b")): "content"}
    (ov,) = report.overlaps
    assert ov.rect_pt[2:] == pytest.approx((50.0, 20.0), abs=0.05)


# ------------------------------------------------------------------------------- touch
def test_one_point_graze_is_a_touch(facade, tmp_path) -> None:  # noqa: ANN001
    """Boxes that bite by a single point: below anything a rasterized edge could show."""
    report = _inspect(
        facade,
        tmp_path,
        _rect("a", "top: parent.top+40pt, left: parent.left+40pt")
        + _rect("b", "top: a.bottom-1pt, left: parent.left+40pt"),
    )
    assert _kinds(report) == {frozenset(("a", "b")): "touch"}
    (ov,) = report.overlaps
    assert ov.rect_pt[3] == pytest.approx(1.0, abs=0.05)


def test_corner_nick_under_two_percent_of_the_smaller_box_is_a_touch(facade, tmp_path) -> None:  # noqa: ANN001
    """An 8x8pt corner overlap of two 100x40pt boxes is 1.6% of either: a nudge, not a re-layout."""
    report = _inspect(
        facade,
        tmp_path,
        _rect("a", "top: parent.top+40pt, left: parent.left+40pt")
        + _rect("b", "top: a.bottom-8pt, left: a.right-8pt"),
    )
    assert _kinds(report) == {frozenset(("a", "b")): "touch"}


def test_four_point_bite_between_text_lines_stays_content(facade, tmp_path) -> None:  # noqa: ANN001
    """The genuine case the ``touch`` threshold must never swallow: 10% of the smaller box."""
    report = _inspect(
        facade,
        tmp_path,
        _text("venue-1", "top: parent.top+100pt, left: parent.left+20pt")
        + _text("venue-2", "top: venue-1.bottom-4pt, left: parent.left+20pt"),
    )
    assert _kinds(report) == {frozenset(("venue-1", "venue-2")): "content"}


# ------------------------------------------------------------- text extent (shaped width)
def _word(node_id: str, anchor: str, align: str, direction: str = "auto", extra: str = "") -> str:
    """A two-letter word in a 300pt-wide box, so the box says little about where the ink is."""
    return (
        f"    - id: {node_id}\n      type: text\n      text: Hi\n"
        "      style: {font: Inter, font_size: 14pt, color: '#000000'}\n"
        f"      paragraph: {{align: {align}, direction: {direction}}}\n"
        f"{extra}"
        f"      constraints: {{anchor: {{{anchor}}}, size: {{w: 300pt, h: 40pt}}}}\n"
    )


_RULE_LEFT = _rect("rule-left", "top: parent.top+110pt, left: parent.left+50pt",
                   size="{w: 60pt, h: 3pt}")
_RULE_RIGHT = _rect("rule-right", "top: parent.top+110pt, left: parent.left+290pt",
                    size="{w: 60pt, h: 3pt}")


def test_centred_word_does_not_collide_with_rules_under_its_box_ends(facade, tmp_path) -> None:  # noqa: ANN001
    """The shaped width is known, so a word in the middle of a wide box clears both ends."""
    report = _inspect(
        facade,
        tmp_path,
        _word("word", "top: parent.top+100pt, left: parent.left+50pt", "center")
        + _RULE_LEFT + _RULE_RIGHT,
    )
    assert report.overlaps == []


def test_word_collides_only_at_the_box_end_it_is_aligned_to(facade, tmp_path) -> None:  # noqa: ANN001
    report = _inspect(
        facade,
        tmp_path,
        _word("word", "top: parent.top+100pt, left: parent.left+50pt", "right")
        + _RULE_LEFT + _RULE_RIGHT,
    )
    assert _kinds(report) == {frozenset(("word", "rule-right")): "content"}


def test_start_alignment_follows_the_paragraph_direction(facade, tmp_path) -> None:  # noqa: ANN001
    """Under ``direction: rtl`` a ``start``-aligned word sits at the box's right end."""
    report = _inspect(
        facade,
        tmp_path,
        _word("word", "top: parent.top+100pt, left: parent.left+50pt", "start", direction="rtl")
        + _RULE_LEFT + _RULE_RIGHT,
    )
    assert _kinds(report) == {frozenset(("word", "rule-right")): "content"}


def test_rotated_text_keeps_its_whole_box_for_collision(facade, tmp_path) -> None:  # noqa: ANN001
    """A rotated node's alignment offset is not axis-aligned, so its AABB is kept (conservative)."""
    report = _inspect(
        facade,
        tmp_path,
        _word("word", "top: parent.top+100pt, left: parent.left+50pt", "center",
              extra="      transform: {rotate: 180}\n")
        + _RULE_LEFT,
    )
    assert _kinds(report) == {frozenset(("word", "rule-left")): "content"}

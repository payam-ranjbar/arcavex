"""Vertical stack layout through the real text stack (audit A2).

A speaker card's name, role and talking point keep one gap whatever the name's line count, the
gap follows a format patch, and an RTL locale packs the stack from the right edge. These are the
measurements the golden images in tests/golden/test_goldens.py picture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import LayoutNodeReport

_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "stack-card"
_TEMPLATE = _FIXTURE / "template.yaml"
_ORDER = ("name", "rule", "role", "bullet")


def _nodes(data: str, format_name: str, locale: str) -> dict[str, LayoutNodeReport]:
    report = build_facade().inspect_layout(_TEMPLATE, _FIXTURE / data, format_name, locale)
    assert report.ok, report.diagnostics
    assert report.root is not None
    found: dict[str, LayoutNodeReport] = {}

    def walk(node: LayoutNodeReport) -> None:
        found[node.id] = node
        for child in node.children:
            walk(child)

    walk(report.root)
    return found


def _gaps(nodes: dict[str, LayoutNodeReport]) -> list[float]:
    """Vertical space between consecutive stack children, in pt."""
    gaps = []
    for upper, lower in zip(_ORDER, _ORDER[1:]):
        ux, uy, uw, uh = nodes[upper].bounds_pt
        gaps.append(round(nodes[lower].bounds_pt[1] - (uy + uh), 2))
    return gaps


def test_gap_is_even_for_a_one_line_and_a_two_line_name() -> None:
    short = _nodes("data-short.yaml", "square", "en")
    long = _nodes("data-long.yaml", "square", "en")
    # The two-line name is taller, and everything below it moves down by exactly that much.
    grown = long["name"].bounds_pt[3] - short["name"].bounds_pt[3]
    assert grown > 20
    assert long["role"].bounds_pt[1] - short["role"].bounds_pt[1] == pytest.approx(grown)
    # 14px at 96 dpi is 10.5pt, between every pair, in both cases.
    assert _gaps(short) == [10.5, 10.5, 10.5]
    assert _gaps(long) == [10.5, 10.5, 10.5]


def test_stack_hugs_its_children() -> None:
    nodes = _nodes("data-long.yaml", "square", "en")
    card = nodes["card"].bounds_pt
    bullet = nodes["bullet"].bounds_pt
    # fit_content on the stack: bottom padding (20px = 15pt) below the last child.
    assert card[1] + card[3] == pytest.approx(bullet[1] + bullet[3] + 15.0)


def test_format_patch_overrides_the_gap() -> None:
    story = _nodes("data-long.yaml", "story", "en")
    # The story format patches nodes.card.gap to 36px = 27pt; square keeps 10.5pt.
    assert _gaps(story) == [27.0, 27.0, 27.0]


def test_rtl_locale_packs_children_from_the_right() -> None:
    nodes = _nodes("data-short.yaml", "square", "fa")
    card = nodes["card"].bounds_pt
    # The card's `start` anchor resolves to the right edge under rtl: 40px (30pt) inset.
    assert card[0] + card[2] == pytest.approx(360.0 - 30.0)
    # cross_align: start puts every child against the card's right padding (20px = 15pt).
    right = card[0] + card[2] - 15.0
    for node_id in _ORDER:
        x, _, w, _ = nodes[node_id].bounds_pt
        assert x + w == pytest.approx(right, abs=0.01), node_id
    assert _gaps(nodes) == [10.5, 10.5, 10.5]

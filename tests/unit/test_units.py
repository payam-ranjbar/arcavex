"""Unit conversion and geometry tests."""

from __future__ import annotations

import math

import pytest

from arcavex.kernel.ir.units import (
    Dim,
    Insets,
    Matrix3,
    Rect,
    Unit,
    mm_to_pt,
    pt_to_px,
    px_to_pt,
)


def test_parse_bare_number_is_px() -> None:
    assert Dim.parse(1080) == Dim(1080.0, Unit.PX)
    assert Dim.parse("1080") == Dim(1080.0, Unit.PX)


def test_parse_units() -> None:
    assert Dim.parse("40pt") == Dim(40.0, Unit.PT)
    assert Dim.parse("210mm") == Dim(210.0, Unit.MM)
    assert Dim.parse("62%") == Dim(62.0, Unit.PERCENT)
    assert Dim.parse(" -3.5mm ") == Dim(-3.5, Unit.MM)


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        Dim.parse("nonsense")
    with pytest.raises(ValueError):
        Dim.parse(True)


def test_pt_conversion() -> None:
    assert Dim.parse("72pt").to_pt(96) == 72.0
    assert math.isclose(Dim.parse("25.4mm").to_pt(96), 72.0)
    assert math.isclose(Dim.parse("96px").to_pt(96), 72.0)


def test_percent_requires_basis() -> None:
    with pytest.raises(ValueError):
        Dim.parse("50%").to_pt(96)
    assert Dim.parse("50%").to_pt(96, percent_basis_pt=200.0) == 100.0


def test_px_pt_roundtrip() -> None:
    assert math.isclose(pt_to_px(px_to_pt(120.0, 96), 96), 120.0)
    assert math.isclose(mm_to_pt(25.4), 72.0)


def test_rect_edges() -> None:
    rect = Rect(10, 20, 100, 40)
    assert rect.right == 110
    assert rect.bottom == 60
    assert rect.center_x == 60
    assert rect.center_y == 40


def test_rect_expanded() -> None:
    rect = Rect(0, 0, 100, 100).expanded(Insets(5, 10, 5, 10))
    assert (rect.x, rect.y, rect.w, rect.h) == (-10, -5, 120, 110)


def test_matrix_translation_and_apply() -> None:
    m = Matrix3.translation(5, 7)
    assert m.apply(1, 2) == (6, 9)


def test_matrix_compose_order() -> None:
    first = Matrix3.translation(10, 0)
    second = Matrix3.translation(0, 5)
    composed = first.then(second)
    assert composed.apply(0, 0) == (10, 5)

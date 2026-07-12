"""Property-based tests for unit conversion (round-trip and associativity)."""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from arcavex.kernel.ir.units import Dim, Unit, mm_to_pt, pt_to_px, px_to_pt

_finite = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)
_dpi = st.integers(min_value=36, max_value=1200)


@given(px=_finite, dpi=_dpi)
def test_px_pt_roundtrip(px: float, dpi: int) -> None:
    assert math.isclose(pt_to_px(px_to_pt(px, dpi), dpi), px, rel_tol=1e-9, abs_tol=1e-9)


@given(value=_finite, dpi=_dpi)
def test_parse_numeric_to_pt_matches_direct(value: float, dpi: int) -> None:
    # Bare numbers parse as pixels; conversion must match the direct px->pt helper.
    dim = Dim.parse(value)
    assert math.isclose(dim.to_pt(dpi), px_to_pt(value, dpi), rel_tol=1e-9, abs_tol=1e-9)


@given(mm=_finite)
def test_mm_conversion_is_linear(mm: float) -> None:
    assert math.isclose(mm_to_pt(mm) * 2, mm_to_pt(mm * 2), rel_tol=1e-9, abs_tol=1e-9)


@given(value=_finite, dpi=_dpi)
def test_pt_unit_is_identity(value: float, dpi: int) -> None:
    assert Dim(value, Unit.PT).to_pt(dpi) == value

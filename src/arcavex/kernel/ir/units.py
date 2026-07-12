"""Physical dimensions, unit conversion, and geometric value types.

All authored dimensions are physical units (``mm``, ``pt``, ``px``) or ``%`` of the
parent. Absolute units resolve to points; the renderer maps points to device pixels via
DPI at render time. Percentages are relative and resolve against a parent basis during
layout. This module is dependency-free (stdlib only) so the IR stays pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


class Unit(StrEnum):
    """A supported dimension unit."""

    MM = "mm"
    PT = "pt"
    PX = "px"
    PERCENT = "%"


_DIM_RE = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*(mm|pt|px|%)?\s*$")


def px_to_pt(px: float, dpi: float) -> float:
    """Convert a pixel measurement to points at the given DPI."""
    return px * PT_PER_INCH / dpi


def pt_to_px(pt: float, dpi: float) -> float:
    """Convert a point measurement to pixels at the given DPI."""
    return pt * dpi / PT_PER_INCH


def mm_to_pt(mm: float) -> float:
    """Convert millimetres to points."""
    return mm * PT_PER_INCH / MM_PER_INCH


@dataclass(frozen=True)
class Dim:
    """An authored dimension: a value paired with a unit.

    Bare numbers (no unit suffix) are interpreted as pixels, consistent with the
    authoring format where ``1080`` and ``1080px`` are equivalent.
    """

    value: float
    unit: Unit

    @classmethod
    def parse(cls, raw: str | int | float) -> Dim:
        """Parse a dimension from a string or bare number.

        Args:
            raw: A value such as ``"40pt"``, ``"210mm"``, ``"62%"``, ``120``, or
                ``"120"``. Bare numbers are pixels.

        Returns:
            The parsed :class:`Dim`.

        Raises:
            ValueError: If the string is not a valid dimension.
        """
        if isinstance(raw, bool):  # bool is an int subclass; reject it explicitly
            raise ValueError(f"invalid dimension: {raw!r}")
        if isinstance(raw, (int, float)):
            return cls(float(raw), Unit.PX)
        match = _DIM_RE.match(raw)
        if match is None:
            raise ValueError(f"invalid dimension: {raw!r}")
        number = float(match.group(1))
        suffix = match.group(2)
        unit = Unit(suffix) if suffix else Unit.PX
        return cls(number, unit)

    @property
    def is_relative(self) -> bool:
        """Whether this dimension needs a parent basis to resolve (percent)."""
        return self.unit is Unit.PERCENT

    def to_pt(self, dpi: float, percent_basis_pt: float | None = None) -> float:
        """Resolve this dimension to points.

        Args:
            dpi: Dots per inch used to convert pixel units.
            percent_basis_pt: The parent extent in points, required only when the unit
                is a percentage.

        Returns:
            The dimension in points.

        Raises:
            ValueError: If a percentage is resolved without a basis.
        """
        if self.unit is Unit.PT:
            return self.value
        if self.unit is Unit.MM:
            return mm_to_pt(self.value)
        if self.unit is Unit.PX:
            return px_to_pt(self.value, dpi)
        if percent_basis_pt is None:
            raise ValueError("percentage dimension requires a parent basis")
        return percent_basis_pt * self.value / 100.0

    def canonical(self, dpi: float) -> str:
        """Return a canonical string form (absolute units normalized to points)."""
        if self.unit is Unit.PERCENT:
            return f"{_norm_float(self.value)}%"
        return f"{_norm_float(self.to_pt(dpi))}pt"


@dataclass(frozen=True)
class Insets:
    """Directional inset lengths in points (top, right, bottom, left)."""

    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    left: float = 0.0

    @property
    def horizontal(self) -> float:
        """Combined left + right inset."""
        return self.left + self.right

    @property
    def vertical(self) -> float:
        """Combined top + bottom inset."""
        return self.top + self.bottom


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in points."""

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        """Right edge (x + w)."""
        return self.x + self.w

    @property
    def bottom(self) -> float:
        """Bottom edge (y + h)."""
        return self.y + self.h

    @property
    def center_x(self) -> float:
        """Horizontal centre."""
        return self.x + self.w / 2.0

    @property
    def center_y(self) -> float:
        """Vertical centre."""
        return self.y + self.h / 2.0

    def expanded(self, insets: Insets) -> Rect:
        """Return this rectangle grown outward by ``insets``."""
        return Rect(
            self.x - insets.left,
            self.y - insets.top,
            self.w + insets.horizontal,
            self.h + insets.vertical,
        )


@dataclass(frozen=True)
class Matrix3:
    """A 2D affine transform stored as six components (row-major a,b,c,d,e,f).

    Maps a point ``(x, y)`` to ``(a*x + c*y + e, b*x + d*y + f)``.
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @classmethod
    def identity(cls) -> Matrix3:
        """Return the identity transform."""
        return cls()

    @classmethod
    def translation(cls, dx: float, dy: float) -> Matrix3:
        """Return a translation transform."""
        return cls(1.0, 0.0, 0.0, 1.0, dx, dy)

    def then(self, other: Matrix3) -> Matrix3:
        """Compose so ``self`` is applied first, then ``other``."""
        return Matrix3(
            a=other.a * self.a + other.c * self.b,
            b=other.b * self.a + other.d * self.b,
            c=other.a * self.c + other.c * self.d,
            d=other.b * self.c + other.d * self.d,
            e=other.a * self.e + other.c * self.f + other.e,
            f=other.b * self.e + other.d * self.f + other.f,
        )

    def apply(self, x: float, y: float) -> tuple[float, float]:
        """Transform a point."""
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        """Return the six components as a tuple."""
        return (self.a, self.b, self.c, self.d, self.e, self.f)


def _norm_float(value: float) -> str:
    """Normalize a float to a stable string: round to 6 dp, strip trailing zeros."""
    rounded = round(value, 6)
    if rounded == 0.0:
        rounded = 0.0  # collapse -0.0
    text = f"{rounded:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"

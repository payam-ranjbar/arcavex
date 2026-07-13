"""Mask-generator implementations and their parameter schemas.

Mask dimensions are expressed in points (a bare number means points; ``pt``/``mm`` suffixes
are accepted; ``px``/``%`` are rejected so a mask never depends on render DPI). Each generator
builds a :class:`skia.Path` in the node's point-space bounds; the renderer clips content to it.
"""

from __future__ import annotations

import math
from typing import Annotated, ClassVar

import skia  # type: ignore[import-untyped]
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from arcavex.kernel.contracts.spi import MaskGenerator
from arcavex.kernel.ir.units import Dim, Rect


def _as_pt(value: object) -> float:
    """Coerce a mask dimension to points; reject relative/pixel units for DPI-independence."""
    if isinstance(value, bool):
        raise ValueError("expected a length, got a boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        dim = Dim.parse(value)
        if dim.unit.value in {"px", "%"}:
            raise ValueError(f"mask lengths must be pt or mm, not {dim.unit.value!r}")
        return dim.to_pt(72.0)
    raise ValueError(f"invalid length {value!r}")


Points = Annotated[float, BeforeValidator(_as_pt)]


class RoundedRectParams(BaseModel):
    """Parameters for the ``rounded_rect`` mask."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    radius: Points = Field(default=0.0, ge=0.0)


class RoundedRectMask(MaskGenerator):
    """Clips to the node's bounds with rounded corners of a fixed point radius."""

    name: ClassVar[str] = "rounded_rect"
    param_schema: ClassVar[type[BaseModel]] = RoundedRectParams

    def build(self, params: BaseModel, bounds: Rect) -> skia.Path:
        """Build a rounded-rectangle clip path."""
        assert isinstance(params, RoundedRectParams)
        radius = min(params.radius, bounds.w / 2.0, bounds.h / 2.0)
        path = skia.Path()
        path.addRoundRect(
            skia.Rect.MakeXYWH(bounds.x, bounds.y, bounds.w, bounds.h), radius, radius
        )
        return path


class CircleParams(BaseModel):
    """Parameters for the ``circle`` mask (an inscribed ellipse; no tunables in v1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CircleMask(MaskGenerator):
    """Clips to the largest ellipse inscribed in the node's bounds."""

    name: ClassVar[str] = "circle"
    param_schema: ClassVar[type[BaseModel]] = CircleParams

    def build(self, params: BaseModel, bounds: Rect) -> skia.Path:
        """Build an inscribed-ellipse clip path."""
        path = skia.Path()
        path.addOval(skia.Rect.MakeXYWH(bounds.x, bounds.y, bounds.w, bounds.h))
        return path


class DiamondGridParams(BaseModel):
    """Parameters for the ``diamond_grid`` mask.

    ``cell`` is the square side, ``gutter`` the gap between cells (both in points), and
    ``angle`` the rotation in degrees that turns the squares into diamonds (45° default).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cell: Points = Field(default=90.0, gt=0.0)
    gutter: Points = Field(default=6.0, ge=0.0)
    angle: float = Field(default=45.0)


class DiamondGridMask(MaskGenerator):
    """Clips to a lattice of rotated squares, leaving the gutters as gaps.

    The reference-poster photo treatment: an image placed behind this mask shows through the
    diamond cells while the background shows through the diagonal gutters between them.
    """

    name: ClassVar[str] = "diamond_grid"
    param_schema: ClassVar[type[BaseModel]] = DiamondGridParams

    def build(self, params: BaseModel, bounds: Rect) -> skia.Path:
        """Build the diamond-lattice clip path covering ``bounds``."""
        assert isinstance(params, DiamondGridParams)
        cell, gutter, angle = params.cell, params.gutter, params.angle
        pitch = cell + gutter
        half = cell / 2.0
        cx, cy = bounds.center_x, bounds.center_y
        rad = math.radians(angle)
        cos, sin = math.cos(rad), math.sin(rad)
        # Cover the bounds even after rotation: step across its diagonal in both directions.
        reach = int(math.hypot(bounds.w, bounds.h) / pitch) + 2
        path = skia.Path()
        corners = ((-half, -half), (half, -half), (half, half), (-half, half))
        for i in range(-reach, reach + 1):
            for j in range(-reach, reach + 1):
                lx, ly = i * pitch, j * pitch
                pts = []
                for dx, dy in corners:
                    gx, gy = lx + dx, ly + dy
                    rx = gx * cos - gy * sin
                    ry = gx * sin + gy * cos
                    pts.append(skia.Point(cx + rx, cy + ry))
                path.addPoly(pts, True)
        return path


def builtin_masks() -> list[MaskGenerator]:
    """Return the built-in mask generators for registration."""
    return [RoundedRectMask(), CircleMask(), DiamondGridMask()]

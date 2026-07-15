"""Shared pydantic field types for effect parameter schemas.

Effect params are authored YAML: colors as hex/``rgba()`` strings, lengths as ``pt``/``mm``
numbers. These validators normalize them the same way the rest of the compiler does — a
length is DPI-independent points (``px``/``%`` rejected, as for masks) and a color is a
straight-alpha RGBA tuple — so an effect schema reads declaratively.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

from arcavex.kernel.ir.colors import Color
from arcavex.kernel.ir.units import Dim

RGBA = tuple[float, float, float, float]


def _as_pt(value: object) -> float:
    """Coerce an effect length to points; reject relative/pixel units for DPI-independence."""
    if isinstance(value, bool):
        raise ValueError("expected a length, got a boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        dim = Dim.parse(value)
        if dim.unit.value in {"px", "%"}:
            raise ValueError(f"effect lengths must be pt or mm, not {dim.unit.value!r}")
        return dim.to_pt(72.0)
    raise ValueError(f"invalid length {value!r}")


def _as_rgba(value: object) -> RGBA:
    """Coerce a color string (hex / rgba() / named) to a straight-alpha RGBA tuple."""
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        chans = [float(c) for c in value]
        if len(chans) == 3:
            chans.append(1.0)
        return (chans[0], chans[1], chans[2], chans[3])
    if isinstance(value, str):
        return Color.parse(value).as_tuple()
    raise ValueError(f"invalid color {value!r}")


Points = Annotated[float, BeforeValidator(_as_pt)]
RGBAColor = Annotated[RGBA, BeforeValidator(_as_rgba)]

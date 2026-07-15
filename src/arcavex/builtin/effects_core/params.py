"""Shared pydantic field types for effect parameter schemas.

Effect params are authored YAML: colors as hex/``rgba()`` strings, lengths as ``pt``/``mm``/
``px`` numbers. These validators normalize them the same way the rest of the compiler does — a
length is stored as DPI-independent points and a color is a straight-alpha RGBA tuple — so an
effect schema reads declaratively. A ``px`` length is converted to points using the canvas DPI
passed in the validation context (default 72 when validated outside a compile, e.g. unit tests),
so ``px`` works consistently with the rest of the authoring surface; only relative ``%`` is
rejected, since an effect length has no percentage basis.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator, ValidationInfo

from arcavex.kernel.ir.colors import Color
from arcavex.kernel.ir.units import Dim

RGBA = tuple[float, float, float, float]


def _context_dpi(info: ValidationInfo) -> float:
    """Read the canvas DPI from the validation context, defaulting to 72 (pt == px)."""
    context = getattr(info, "context", None)
    if isinstance(context, dict):
        dpi = context.get("dpi")
        if isinstance(dpi, (int, float)) and dpi > 0:
            return float(dpi)
    return 72.0


def _as_pt(value: object, info: ValidationInfo) -> float:
    """Coerce an effect length to points (pt/mm/px); reject only relative ``%`` units.

    ``px`` is converted to points with the canvas DPI supplied in the validation context, so an
    effect length authored in ``px`` lands at the same physical size as a ``px`` used anywhere
    else in the template.
    """
    if isinstance(value, bool):
        raise ValueError("expected a length, got a boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        dim = Dim.parse(value)
        if dim.unit.value == "%":
            raise ValueError("effect lengths must be an absolute unit (pt, mm, or px), not '%'")
        return dim.to_pt(_context_dpi(info))
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

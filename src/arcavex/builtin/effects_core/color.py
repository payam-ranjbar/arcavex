"""Color-category effects: grade, duotone, threshold, posterize.

Each returns a :class:`ColorTransform` — a 4x5 matrix (cross-channel linear) or a per-channel
256-entry table (separable non-linear) — so the renderer can fuse a run of them into one Skia
color filter applied in a single pass (spec §4.4). Matrices operate on **unpremultiplied**
RGBA in [0, 1] (Skia un/repremultiplies around the filter, spec §3.1.3), so authors reason in
straight alpha. Luminance-driven, non-separable mapping (palette-map) is a raster effect
instead — see :mod:`arcavex.builtin.effects_core.raster`.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from arcavex.builtin.effects_core.context import (
    LUMA,
    ColorContext,
    ColorMatrix,
    ColorTable,
    ColorTransform,
    compose_color_matrices,
)
from arcavex.builtin.effects_core.params import RGBAColor
from arcavex.kernel.contracts.spi import Effect
from arcavex.kernel.contracts.types import EffectKind
from arcavex.kernel.ir.units import Insets


class _ColorEffect(Effect):
    """Base for color effects: no bounds expansion, ``apply`` narrows the context."""

    kind: ClassVar[EffectKind] = EffectKind.COLOR

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Color effects recolor in place and never grow the paint region."""
        return Insets()


# ------------------------------------------------------------------------------- grade
class GradeParams(BaseModel):
    """Tone controls: additive ``brightness``, ``contrast`` about mid-grey, and ``saturation``.

    All three are linear, so grade is a single matrix that fuses with neighbouring color
    effects. (Non-linear ``gamma`` is deliberately excluded to keep the color category fusable;
    author a gamma-style look with contrast + brightness.)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    brightness: float = Field(default=0.0, ge=-1.0, le=1.0)
    contrast: float = Field(default=1.0, ge=0.0, le=4.0)
    saturation: float = Field(default=1.0, ge=0.0, le=4.0)


class Grade(_ColorEffect):
    """Brightness/contrast/saturation as one fused color matrix."""

    param_schema: ClassVar[type[BaseModel]] = GradeParams

    def apply(self, ctx: object) -> ColorTransform:
        """Return the composed grade matrix (saturation, then contrast, then brightness)."""
        assert isinstance(ctx, ColorContext)
        p = ctx.params
        assert isinstance(p, GradeParams)
        sat = _saturation_matrix(p.saturation)
        con = _contrast_matrix(p.contrast)
        bri = _brightness_matrix(p.brightness)
        return compose_color_matrices(compose_color_matrices(sat, con), bri)


# ----------------------------------------------------------------------------- duotone
class DuotoneParams(BaseModel):
    """Map luminance to a gradient from ``shadow`` (dark) to ``highlight`` (light)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    shadow: RGBAColor = Field(default=(0.1, 0.0, 0.2, 1.0))
    highlight: RGBAColor = Field(default=(1.0, 0.85, 0.0, 1.0))


class Duotone(_ColorEffect):
    """Luminance-to-gradient duotone as a single color matrix (alpha preserved)."""

    param_schema: ClassVar[type[BaseModel]] = DuotoneParams

    def apply(self, ctx: object) -> ColorTransform:
        """Return the duotone matrix ``shadow + luma*(highlight - shadow)``."""
        assert isinstance(ctx, ColorContext)
        p = ctx.params
        assert isinstance(p, DuotoneParams)
        s, h = p.shadow, p.highlight
        wr, wg, wb = LUMA
        rows: list[float] = []
        for i in range(3):  # r, g, b out-channels
            d = h[i] - s[i]
            rows.extend([d * wr, d * wg, d * wb, 0.0, s[i]])
        rows.extend([0.0, 0.0, 0.0, 1.0, 0.0])  # alpha passthrough
        return ColorMatrix(tuple(rows))


# --------------------------------------------------------------------------- threshold
class ThresholdParams(BaseModel):
    """Per-channel binarization at ``level``; below → ``low``, at/above → ``high``.

    A separable (per-channel) threshold, so it is a color table rather than a raster pass; it
    delivers the hard, high-contrast ink look while still composing in the color stage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: float = Field(default=0.5, ge=0.0, le=1.0)
    low: float = Field(default=0.0, ge=0.0, le=1.0)
    high: float = Field(default=1.0, ge=0.0, le=1.0)


class Threshold(_ColorEffect):
    """Per-channel threshold as a color table."""

    param_schema: ClassVar[type[BaseModel]] = ThresholdParams

    def apply(self, ctx: object) -> ColorTransform:
        """Return an RGB step table at ``level`` (alpha identity)."""
        assert isinstance(ctx, ColorContext)
        p = ctx.params
        assert isinstance(p, ThresholdParams)
        cut = int(round(p.level * 255))
        lo, hi = int(round(p.low * 255)), int(round(p.high * 255))
        table = tuple(lo if i < cut else hi for i in range(256))
        identity = tuple(range(256))
        return ColorTable(a=identity, r=table, g=table, b=table)


# --------------------------------------------------------------------------- posterize
class PosterizeParams(BaseModel):
    """Quantize each channel to ``levels`` bands (2..64) for a flat, screen-print palette."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    levels: int = Field(default=4, ge=2, le=64)


class Posterize(_ColorEffect):
    """Per-channel quantization as a color table."""

    param_schema: ClassVar[type[BaseModel]] = PosterizeParams

    def apply(self, ctx: object) -> ColorTransform:
        """Return an RGB quantization table (alpha identity)."""
        assert isinstance(ctx, ColorContext)
        p = ctx.params
        assert isinstance(p, PosterizeParams)
        n = p.levels
        table: list[int] = []
        for i in range(256):
            band = int(i * n / 256)
            band = min(band, n - 1)
            value = round(band * 255 / (n - 1)) if n > 1 else 0
            table.append(value)
        quant = tuple(table)
        identity = tuple(range(256))
        return ColorTable(a=identity, r=quant, g=quant, b=quant)


# --------------------------------------------------------------------------- matrix helpers
def _brightness_matrix(amount: float) -> ColorMatrix:
    return ColorMatrix(
        (1.0, 0.0, 0.0, 0.0, amount,
         0.0, 1.0, 0.0, 0.0, amount,
         0.0, 0.0, 1.0, 0.0, amount,
         0.0, 0.0, 0.0, 1.0, 0.0)
    )


def _contrast_matrix(c: float) -> ColorMatrix:
    off = 0.5 * (1.0 - c)
    return ColorMatrix(
        (c, 0.0, 0.0, 0.0, off,
         0.0, c, 0.0, 0.0, off,
         0.0, 0.0, c, 0.0, off,
         0.0, 0.0, 0.0, 1.0, 0.0)
    )


def _saturation_matrix(s: float) -> ColorMatrix:
    wr, wg, wb = LUMA
    inv = 1.0 - s
    return ColorMatrix(
        (inv * wr + s, inv * wg, inv * wb, 0.0, 0.0,
         inv * wr, inv * wg + s, inv * wb, 0.0, 0.0,
         inv * wr, inv * wg, inv * wb + s, 0.0, 0.0,
         0.0, 0.0, 0.0, 1.0, 0.0)
    )

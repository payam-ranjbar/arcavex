"""Composite-category effects: drop-shadow and glow.

A composite effect receives the node's element raster (already covering its expanded paint
region) plus a read-only backdrop snapshot, and returns a raster with the effect composited so
the shadow/glow sits behind the element in z-order (spec §3.2). Both are built from the
element's own alpha via a Skia drop-shadow image filter, so they need no pixel loop. Bounds
expansion is directional and honest: a shadow grows the paint region by its offset plus blur
spread on the side it falls.
"""

from __future__ import annotations

from typing import ClassVar

import skia  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from arcavex.builtin.effects_core.context import CompositeContext, render_to_pool
from arcavex.builtin.effects_core.params import Points, RGBAColor
from arcavex.kernel.contracts.spi import Effect
from arcavex.kernel.contracts.types import EffectKind
from arcavex.kernel.ir.units import Insets
from arcavex.kernel.ir.units import pt_to_px as _pt_to_px

_SPREAD = 3.0  # a Gaussian's visible reach in sigmas


def _color4f(rgba: tuple[float, float, float, float]) -> skia.Color4f:
    return skia.Color4f(rgba[0], rgba[1], rgba[2], rgba[3])


class _CompositeEffect(Effect):
    """Base for composite effects."""

    kind: ClassVar[EffectKind] = EffectKind.COMPOSITE


# ---------------------------------------------------------------------------- drop-shadow
class DropShadowParams(BaseModel):
    """An offset, blurred, tinted copy of the node cast behind it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dx: Points = Field(default=6.0)
    dy: Points = Field(default=8.0)
    blur: Points = Field(default=4.0, ge=0.0)
    color: RGBAColor = Field(default=(0.0, 0.0, 0.0, 0.45))


class DropShadow(_CompositeEffect):
    """Cast a soft shadow behind the element from its alpha."""

    param_schema: ClassVar[type[BaseModel]] = DropShadowParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Grow only toward where the blurred, offset shadow actually falls."""
        assert isinstance(params, DropShadowParams)
        spread = params.blur * _SPREAD
        dx, dy = params.dx, params.dy
        return Insets(
            top=max(0.0, -dy) + spread,
            right=max(0.0, dx) + spread,
            bottom=max(0.0, dy) + spread,
            left=max(0.0, -dx) + spread,
        )

    def apply(self, ctx: object) -> skia.Image:
        """Return the element with its shadow composited behind it."""
        assert isinstance(ctx, CompositeContext)
        p = ctx.params
        assert isinstance(p, DropShadowParams)
        image = ctx.image
        sigma = _pt_to_px(p.blur, ctx.dpi)
        image_filter = skia.ImageFilters.DropShadow(
            _pt_to_px(p.dx, ctx.dpi), _pt_to_px(p.dy, ctx.dpi),
            sigma, sigma, _color4f(p.color).toColor(),
        )

        def draw(canvas: skia.Canvas) -> None:
            paint = skia.Paint()
            paint.setImageFilter(image_filter)
            canvas.drawImage(image, 0, 0, skia.SamplingOptions(), paint)

        return render_to_pool(ctx.pool, image.width(), image.height(), draw)


# ----------------------------------------------------------------------------------- glow
class GlowParams(BaseModel):
    """A soft coloured halo radiating from the node's silhouette."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    radius: Points = Field(default=8.0, ge=0.0)
    color: RGBAColor = Field(default=(1.0, 0.9, 0.3, 0.8))


class Glow(_CompositeEffect):
    """Radiate a coloured glow behind the element from its alpha."""

    param_schema: ClassVar[type[BaseModel]] = GlowParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """The halo reaches ~3 sigma on every side."""
        assert isinstance(params, GlowParams)
        pad = params.radius * _SPREAD
        return Insets(pad, pad, pad, pad)

    def apply(self, ctx: object) -> skia.Image:
        """Return the element with a symmetric coloured glow behind it."""
        assert isinstance(ctx, CompositeContext)
        p = ctx.params
        assert isinstance(p, GlowParams)
        image = ctx.image
        sigma = _pt_to_px(p.radius, ctx.dpi)
        image_filter = skia.ImageFilters.DropShadow(
            0.0, 0.0, sigma, sigma, _color4f(p.color).toColor()
        )

        def draw(canvas: skia.Canvas) -> None:
            paint = skia.Paint()
            paint.setImageFilter(image_filter)
            canvas.drawImage(image, 0, 0, skia.SamplingOptions(), paint)

        return render_to_pool(ctx.pool, image.width(), image.height(), draw)

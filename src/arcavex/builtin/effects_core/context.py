"""Effect execution contexts, color-transform values, and the surface pool.

These are the runtime types the four effect categories exchange with the renderer (spec §3.2).
They are part of the stable extension surface and now live under :mod:`arcavex.sdk`; the
built-in effects and the Skia backend re-export them from here so the SDK an extension imports
and the objects the renderer constructs are one and the same class. See the SDK modules
(:mod:`arcavex.sdk.context`, :mod:`arcavex.sdk.surface`, :mod:`arcavex.sdk.color`,
:mod:`arcavex.sdk.rng`) for the definitions.
"""

from __future__ import annotations

from arcavex.sdk.color import (
    IDENTITY_MATRIX,
    LUMA,
    ColorMatrix,
    ColorTable,
    ColorTransform,
    compose_color_matrices,
)
from arcavex.sdk.context import (
    ColorContext,
    CompositeContext,
    GeometryContext,
    RasterContext,
)
from arcavex.sdk.rng import effect_rng
from arcavex.sdk.surface import (
    SurfacePool,
    image_to_rgba,
    render_to_pool,
    rgba_to_image,
)

__all__ = [
    "IDENTITY_MATRIX",
    "LUMA",
    "ColorContext",
    "ColorMatrix",
    "ColorTable",
    "ColorTransform",
    "CompositeContext",
    "GeometryContext",
    "RasterContext",
    "SurfacePool",
    "compose_color_matrices",
    "effect_rng",
    "image_to_rgba",
    "render_to_pool",
    "rgba_to_image",
]

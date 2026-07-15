"""The per-category execution contexts an effect's ``apply`` receives (spec §3.2).

The kernel :class:`~arcavex.kernel.contracts.spi.Effect` ABC types ``apply(ctx)`` as
``object``; each of the four categories narrows ``ctx`` to one of the dataclasses here. They
carry Skia surfaces/paths and a numpy RNG — implementation detail, not kernel contract — so they
live in the SDK. The renderer constructs the same context objects an extension imports, so an
extension effect's ``isinstance(ctx, RasterContext)`` narrowing is exact.

Determinism (spec §3.2): every effect that needs randomness draws it from ``ctx.rng``, the
per-(node, effect index) generator from :func:`arcavex.sdk.rng.effect_rng` — never from
``random`` or the wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import skia  # type: ignore[import-untyped]

from arcavex.kernel.ir.units import Rect
from arcavex.sdk.surface import SurfacePool


@dataclass(frozen=True)
class GeometryContext:
    """Input to a ``GEOMETRY`` effect: the node path (pre-raster), params, and RNG.

    ``path`` is the node's Skia path in canvas point space; the effect returns a new path.
    ``bounds`` is the node's layout rectangle, handy for scaling displacement to node size.
    """

    path: skia.Path
    params: object
    rng: np.random.Generator
    bounds: Rect


@dataclass(frozen=True)
class ColorContext:
    """Input to a ``COLOR`` effect. Color effects are pure: params in, transform out."""

    params: object


@dataclass(frozen=True)
class RasterContext:
    """Input to a ``RASTER`` effect: the current element raster plus params, RNG, and pool.

    ``image`` is RGBA (straight alpha) covering the node's expanded paint region. ``dpi``
    lets an effect convert point-valued params (e.g. a halftone pitch) to pixels. Effects
    allocate scratch surfaces only from ``pool``.
    """

    image: skia.Image
    params: object
    rng: np.random.Generator
    pool: SurfacePool
    dpi: float


@dataclass(frozen=True)
class CompositeContext:
    """Input to a ``COMPOSITE`` effect: the element raster plus a read-only backdrop accessor.

    ``backdrop`` is reserved for the content painted below the node in z-order (spec §3.2). It
    is a **deferred, read-only accessor that always returns ``None`` in v1** — the renderer does
    not yet snapshot the underlying canvas region, so a composite effect must not rely on it.
    ``dpi`` converts point params (shadow offset, blur radius) to pixels.
    """

    image: skia.Image
    backdrop: skia.Image | None
    params: object
    rng: np.random.Generator
    pool: SurfacePool
    dpi: float


__all__ = [
    "ColorContext",
    "CompositeContext",
    "GeometryContext",
    "RasterContext",
]

"""Effect execution contexts, color-transform values, and the surface pool.

These are the runtime types the four effect categories exchange with the renderer (spec
§3.2). They live beside the built-in effects (not in the pure kernel) because they carry
Skia surfaces, Skia paths, and a numpy RNG — implementation detail, not contract. The kernel
:class:`~arcavex.kernel.contracts.spi.Effect` ABC types ``apply(ctx)`` as ``object``; each
category narrows ``ctx`` to one of the dataclasses here.

Determinism (spec §3.2): every effect that needs randomness draws it from ``ctx.rng``, a
numpy generator seeded from ``sha256(document.seed, node.id, effect_index)`` — never from
``random`` or the wall clock. :func:`effect_rng` is the single seeding site.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import skia  # type: ignore[import-untyped]

from arcavex.kernel.ir.units import Rect

# --------------------------------------------------------------------------- color values


@dataclass(frozen=True)
class ColorMatrix:
    """A 4x5 row-major color matrix applied to **unpremultiplied** RGBA in [0, 1].

    Row ``i`` is ``[m0..m3, m4]`` so ``out_i = m0*r + m1*g + m2*b + m3*a + m4``. This is the
    exact form Skia's ``ColorFilters.Matrix`` consumes; Skia unpremultiplies before applying
    and repremultiplies after (spec §3.1.3), so effect authors reason in straight alpha.
    Consecutive matrices are *fused* by the renderer into one matrix (real associative
    composition), which is what makes the color category's fusion promise honest.
    """

    m: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.m) != 20:
            raise ValueError("a color matrix has exactly 20 entries (4x5, row-major)")


@dataclass(frozen=True)
class ColorTable:
    """A per-channel 256-entry lookup applied independently to A, R, G, B (unpremultiplied).

    Non-linear color effects (threshold, posterize) that cannot be a matrix become a table.
    A table breaks a matrix fusion run but still composes into the single color filter the
    renderer applies in one pass.
    """

    a: tuple[int, ...]
    r: tuple[int, ...]
    g: tuple[int, ...]
    b: tuple[int, ...]


# A color effect returns one of these; the renderer fuses/composes them (see pipeline).
ColorTransform = ColorMatrix | ColorTable

# Rec.709 luminance weights, used by any luminance-based color effect (duotone, grade sat).
LUMA = (0.2126, 0.7152, 0.0722)

IDENTITY_MATRIX = ColorMatrix(
    (1.0, 0.0, 0.0, 0.0, 0.0,
     0.0, 1.0, 0.0, 0.0, 0.0,
     0.0, 0.0, 1.0, 0.0, 0.0,
     0.0, 0.0, 0.0, 1.0, 0.0)
)


def compose_color_matrices(first: ColorMatrix, second: ColorMatrix) -> ColorMatrix:
    """Return the matrix applying ``first`` then ``second`` (real associative composition).

    Each 4x5 matrix is treated as a 5x5 affine with implicit last row ``[0,0,0,0,1]`` acting on
    ``(r, g, b, a, 1)``; the product ``second @ first`` collapses two passes into one. This is
    the arithmetic behind color-effect fusion, so a fused chain is provably identical to
    applying its members in sequence (spec §4.4).
    """
    a = _to_5x5(first.m)
    b = _to_5x5(second.m)
    out = [[sum(b[i][k] * a[k][j] for k in range(5)) for j in range(5)] for i in range(5)]
    flat: list[float] = []
    for i in range(4):
        flat.extend(out[i])
    return ColorMatrix(tuple(flat))


def _to_5x5(m: tuple[float, ...]) -> list[list[float]]:
    rows = [list(m[i * 5:i * 5 + 5]) for i in range(4)]
    rows.append([0.0, 0.0, 0.0, 0.0, 1.0])
    return rows


# --------------------------------------------------------------------------- RNG seeding
def effect_rng(seed: int, node_id: str, effect_index: int) -> np.random.Generator:
    """Return the numpy generator for one effect on one node (spec §3.2 determinism rule).

    Seeded from ``sha256(seed, node_id, effect_index)`` digest bytes — a stable, cross-process
    hash, never Python's salted ``hash()``. Same inputs give a byte-identical stream; a
    different node id or effect position gives an independent one.
    """
    key = f"{seed}\x00{node_id}\x00{effect_index}".encode()
    digest = hashlib.sha256(key).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


# --------------------------------------------------------------------------- surface pool
class SurfacePool:
    """A per-render-job pool of RGBA raster surfaces keyed by ``(width_px, height_px)``.

    Raster effects acquire a working surface and release it when done, so a deep raster chain
    reuses memory instead of accumulating it (spec §4.5). Lifetime is one render call; the
    renderer asserts nothing is outstanding at the end (the leak guard). Acquired surfaces are
    returned cleared to transparent so a reused buffer never leaks prior pixels.
    """

    def __init__(self) -> None:
        """Create an empty pool."""
        self._free: dict[tuple[int, int], list[skia.Surface]] = {}
        self._outstanding = 0
        self.allocated = 0
        self.acquired = 0
        self.reused = 0

    def acquire(self, width_px: int, height_px: int) -> skia.Surface:
        """Return a cleared surface of the given pixel size, reusing a free one when possible."""
        width_px = max(1, width_px)
        height_px = max(1, height_px)
        self.acquired += 1
        self._outstanding += 1
        bucket = self._free.get((width_px, height_px))
        if bucket:
            surface = bucket.pop()
            self.reused += 1
            surface.getCanvas().clear(skia.Color4f(0, 0, 0, 0))
            return surface
        self.allocated += 1
        return skia.Surface(width_px, height_px)

    def release(self, surface: skia.Surface) -> None:
        """Return a surface to the pool for reuse."""
        width_px, height_px = surface.width(), surface.height()
        self._free.setdefault((width_px, height_px), []).append(surface)
        self._outstanding -= 1

    @property
    def outstanding(self) -> int:
        """Number of surfaces acquired but not yet released (must be 0 after a render)."""
        return self._outstanding

    def stats(self) -> dict[str, int]:
        """Return allocation counters for the leak/reuse test."""
        return {
            "allocated": self.allocated,
            "acquired": self.acquired,
            "reused": self.reused,
            "outstanding": self._outstanding,
        }


# --------------------------------------------------------------------------- contexts
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
    The two shipped composite effects (drop-shadow, glow) build entirely from the element's own
    alpha and ignore it. Populating it is tracked in ``docs/backlog.md``. ``dpi`` converts point
    params (shadow offset, blur radius) to pixels.
    """

    image: skia.Image
    backdrop: skia.Image | None
    params: object
    rng: np.random.Generator
    pool: SurfacePool
    dpi: float


# --------------------------------------------------------------------------- helpers
def render_to_pool(
    pool: SurfacePool,
    width_px: int,
    height_px: int,
    draw: object,
) -> skia.Image:
    """Draw onto a pooled surface via ``draw(canvas)`` and return an immutable snapshot.

    The surface is acquired cleared, painted, snapshotted, then released back to the pool. The
    snapshot is taken before release so the returned image is unaffected when the buffer is
    later reused (Skia snapshots are copy-on-write). This is the one raster-allocation path, so
    every raster effect goes through the pool.
    """
    surface = pool.acquire(width_px, height_px)
    draw(surface.getCanvas())  # type: ignore[operator]
    image = surface.makeImageSnapshot()
    pool.release(surface)
    return image


def image_to_rgba(image: skia.Image) -> np.ndarray:
    """Return an ``(H, W, 4)`` uint8 RGBA (straight-alpha) view of ``image`` for numpy effects."""
    return image.toarray(
        colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
    )


def rgba_to_image(array: np.ndarray) -> skia.Image:
    """Build a Skia image from an ``(H, W, 4)`` uint8 RGBA (straight-alpha) numpy array."""
    contiguous = np.ascontiguousarray(array, dtype=np.uint8)
    return skia.Image.fromarray(
        contiguous, colorType=skia.kRGBA_8888_ColorType
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

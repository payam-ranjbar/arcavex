"""The surface pool and the numpy<->Skia raster helpers effects paint through.

A raster or composite effect acquires scratch surfaces only from the per-render
:class:`SurfacePool`, so a deep effect chain reuses memory instead of accumulating it (spec
§4.5). :func:`render_to_pool` is the single raster-allocation path; :func:`image_to_rgba` /
:func:`rgba_to_image` bridge a Skia image to a straight-alpha numpy array for pixel work. These
carry Skia handles, so they live in the SDK (not the pure kernel) but are part of the stable
extension surface.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import skia  # type: ignore[import-untyped]


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


def render_to_pool(
    pool: SurfacePool,
    width_px: int,
    height_px: int,
    draw: Callable[[skia.Canvas], None],
) -> skia.Image:
    """Draw onto a pooled surface via ``draw(canvas)`` and return an immutable snapshot.

    The surface is acquired cleared, painted, snapshotted, then released back to the pool. The
    snapshot is taken before release so the returned image is unaffected when the buffer is
    later reused (Skia snapshots are copy-on-write). This is the one raster-allocation path, so
    every raster effect goes through the pool.
    """
    surface = pool.acquire(width_px, height_px)
    draw(surface.getCanvas())
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
    return skia.Image.fromarray(contiguous, colorType=skia.kRGBA_8888_ColorType)


__all__ = [
    "SurfacePool",
    "image_to_rgba",
    "render_to_pool",
    "rgba_to_image",
]

"""Opaque bounding box of an image's alpha channel.

`fit: contain` and `fit: cover` scale an asset's declared canvas into its box, so transparent
padding around the artwork scales with it and the artwork renders proportionally smaller. The
opaque fraction of the canvas is what distinguishes that case; `ARC-AST-020` reports it.

Measurement only: nothing here trims, crops, or rewrites an asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import skia  # type: ignore[import-untyped]

# A pixel counts as ink at or above this alpha. Anti-aliased artwork commonly carries a border
# of alpha 1-3, and a single such pixel in a corner would expand the box to the whole canvas.
_ALPHA_FLOOR = 8

# Opaque-fraction threshold for ARC-AST-020. Measured against the assets in this repository:
# examples/hello-poster/logo.png is 0.483 and must not warn; the smallest artwork the diagnostic
# targets is 0.197. test_no_bundled_asset_trips_the_warning fails if a bundled asset enters the
# gap, which is what keeps this number derived from measurement.
COVERAGE_WARN_BELOW = 0.40


@dataclass(frozen=True)
class OpaqueBox:
    """The tight bounding box of an image's opaque pixels, in image pixel coordinates."""

    x: int
    y: int
    width: int
    height: int
    canvas_width: int
    canvas_height: int

    @property
    def coverage(self) -> float:
        """Fraction of the declared canvas area the opaque box occupies (0.0-1.0)."""
        canvas_area = self.canvas_width * self.canvas_height
        if canvas_area <= 0:
            return 0.0
        return (self.width * self.height) / canvas_area

    def as_tuple(self) -> tuple[int, int, int, int]:
        """``(x, y, width, height)`` — the form persisted in an asset sidecar."""
        return (self.x, self.y, self.width, self.height)


def opaque_box(path: Path) -> OpaqueBox | None:
    """Return the opaque bounding box of the image at ``path``.

    An image with no transparent pixels returns a full-canvas box (coverage 1.0). ``None`` means
    the box is undefined: a fully transparent image, or one that cannot be decoded here. Decode
    failures are silent because this feeds a warning; the decode guards that raise run at ingest.
    """
    try:
        image = skia.Image.open(str(path))
    except Exception:  # pragma: no cover - decode is guarded at ingest
        return None
    if image is None:  # pragma: no cover - skia returns None for undecodable bytes
        return None
    # isOpaque() reports the declared alpha type, not whether any pixel is transparent, so it is
    # only conclusive when true.
    if image.isOpaque():
        return None
    try:
        array = image.toarray(
            colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
        )
    except Exception:  # pragma: no cover - defensive
        return None
    return _box_from_alpha(array[..., 3], image.width(), image.height())


def _box_from_alpha(alpha: np.ndarray, canvas_width: int, canvas_height: int) -> OpaqueBox | None:
    """Tight box around every pixel at or above the alpha floor, or ``None`` if there are none."""
    ink = alpha >= _ALPHA_FLOOR
    rows = np.flatnonzero(ink.any(axis=1))
    cols = np.flatnonzero(ink.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    left, right = int(cols[0]), int(cols[-1])
    return OpaqueBox(
        x=left,
        y=top,
        width=right - left + 1,
        height=bottom - top + 1,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
    )

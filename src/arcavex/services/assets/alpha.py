"""Opaque bounding box of an image's alpha channel.

`fit: contain` and `fit: cover` scale an asset's **canvas** into its box. When the artwork
occupies only part of that canvas — a 512x512 logo whose mark is a 452x114 band, the rest
transparent padding — the engine does exactly as instructed and the result is an unreadable
smudge, with nothing wrong to report. That is the one silent-wrong-output trap the readiness
audit found: correct behaviour, useless render, no diagnostic.

The signal that separates it from a normal image is cheap and objective: what fraction of the
declared canvas is actually opaque. This module computes it, and `ARC-AST-020` reports it.

Deliberately *not* an image-processing feature. It measures; it never trims, crops, or alters
a single byte. Fixing the asset stays the author's decision, which keeps the engine
deterministic and the warning honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import skia  # type: ignore[import-untyped]

# A pixel counts as ink above this alpha. Not 0: PNG exporters routinely leave a halo of
# alpha 1-3 around anti-aliased artwork, and one such pixel in a corner would inflate the
# bounding box to the whole canvas and silence the warning exactly when it is most needed.
_ALPHA_FLOOR = 8

# Below this fraction of opaque canvas, `contain`/`cover` are scaling mostly padding.
#
# The readiness audit proposed ~0.60. Measured against every asset shipped in this repository,
# that fires on `examples/hello-poster/logo.png` — 872x581 of artwork in a 1024x1024 canvas,
# 0.483 — which is a real but minor loss of size, not the failure this warning is for. A
# warning that fires on the project's own quick-start teaches the reader to ignore it, so the
# threshold is set below that measurement rather than above the audit's estimate.
#
# 0.40 keeps a clear gap on both sides: the case that prompted the diagnostic measured 0.197,
# and no bundled asset measures between 0.40 and 0.483. `test_no_bundled_asset_trips_the_warning`
# fails if a future asset lands in that gap, so this number stays calibrated against reality
# instead of drifting.
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

    An image with no transparency returns a full-canvas box (coverage 1.0), which is the honest
    answer rather than a special case. ``None`` means the question could not be answered at
    all: an image that is entirely transparent, or one this process cannot decode. A diagnostic
    about image *content* must never be the reason a render fails, so decode problems here are
    silence, not errors — the real decode guards run at ingest and raise properly.

    Note ``skia.Image.isOpaque()`` reports the declared alpha *type*, not whether any pixel is
    actually transparent, so it is only usable as a fast path when it is true.
    """
    try:
        image = skia.Image.open(str(path))
    except Exception:  # pragma: no cover - defensive: decode is guarded at ingest
        return None
    if image is None:  # pragma: no cover - skia returns None for undecodable bytes
        return None
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

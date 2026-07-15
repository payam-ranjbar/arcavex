"""``paper-texture`` — a raster effect that lays seeded paper grain and fibre over a node.

A reviewed reference extension (spec §11 Phase 6 exit). It shows the shape of a real raster
effect: a typed parameter schema, an honest ``bounds_expansion`` (this effect stays inside the
node, so it declares zero), and randomness drawn exclusively from the seeded ``ctx.rng`` so a
fixed document seed renders byte-identical output. It imports **only** ``arcavex.sdk``.

The look combines three deterministic passes over the straight-alpha RGBA raster:

* a fine monochrome **grain** (per-pixel luminance jitter),
* soft directional **fibre** streaks (low-frequency row/column modulation), and
* a subtle **warmth** tint toward cream.

Alpha is never touched, so the effect recolours content without changing its silhouette — which
is exactly why its declared bounds expansion is zero and honest.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from arcavex.sdk import (
    BaseModel,
    ConfigDict,
    Effect,
    EffectKind,
    Field,
    Insets,
    RasterContext,
    image_to_rgba,
    rgba_to_image,
)


class PaperTextureParams(BaseModel):
    """Parameters for the paper-texture effect.

    ``grain`` is the amplitude of the fine per-pixel noise, ``fibre`` the strength of the soft
    directional streaks, and ``warmth`` how far the tint pushes toward cream — all in [0, 1].
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    grain: float = Field(default=0.06, ge=0.0, le=1.0)
    fibre: float = Field(default=0.10, ge=0.0, le=1.0)
    warmth: float = Field(default=0.08, ge=0.0, le=1.0)


class PaperTexture(Effect):
    """Overlay seeded paper grain, fibre streaks, and a warm tint on the node raster."""

    kind: ClassVar[EffectKind] = EffectKind.RASTER
    param_schema: ClassVar[type[BaseModel]] = PaperTextureParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Zero — the effect paints only within the node's own pixels (honest, no outward spread)."""
        return Insets()

    def apply(self, ctx: object) -> object:
        """Return the raster with grain, fibre, and warmth applied; alpha is preserved."""
        assert isinstance(ctx, RasterContext)
        params = ctx.params
        assert isinstance(params, PaperTextureParams)
        rgba = image_to_rgba(ctx.image)
        rgb = rgba[..., :3].astype(np.float32)
        h, w = rgb.shape[:2]

        # Fine grain: one shared monochrome field jitters all three channels together, so the
        # texture reads as paper tooth rather than colour noise. Drawn from the seeded RNG.
        grain = ctx.rng.normal(0.0, params.grain * 255.0, size=(h, w, 1)).astype(np.float32)

        # Fibre: independent low-frequency 1-D fields along each axis, broadcast into streaks.
        row_field = _smooth(ctx.rng.normal(0.0, 1.0, size=h).astype(np.float32))
        col_field = _smooth(ctx.rng.normal(0.0, 1.0, size=w).astype(np.float32))
        fibre = (row_field[:, None] + col_field[None, :])[..., None] * (params.fibre * 40.0)

        # Warmth: a fixed nudge toward cream (lift red, drop blue), scaled by the warmth param.
        warm = np.array([12.0, 4.0, -10.0], dtype=np.float32) * params.warmth

        out = np.clip(rgb + grain + fibre + warm, 0.0, 255.0).astype(np.uint8)
        result = rgba.copy()
        result[..., :3] = out
        return rgba_to_image(result)


def _smooth(values: np.ndarray) -> np.ndarray:
    """Return a 3-tap moving-average of a 1-D field (turns white noise into soft streaks)."""
    kernel = np.array([0.25, 0.5, 0.25], dtype=np.float32)
    return np.convolve(values, kernel, mode="same")

"""A deterministic limited-ink editorial print treatment for photographic assets.

The effect compresses a source image into a warm paper / deep ink tonal range, carries cool
source highlights into a third electric ink, adds a small edge misregistration, and finishes
with a restrained screen plus seeded paper speckle.  It is intentionally implemented through
the public Arcavex SDK so the poster exercises the same extension path available to authors.
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
    Points,
    RGBAColor,
    RasterContext,
    image_to_rgba,
    rgba_to_image,
)


class ArchivePrintParams(BaseModel):
    """The three inks and physical-print artifacts exposed to the template author."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    shadow: RGBAColor = "#07142E"
    paper: RGBAColor = "#F4EAD2"
    accent: RGBAColor = "#00D9FF"
    levels: int = Field(default=5, ge=2, le=12)
    contrast: float = Field(default=1.18, ge=0.25, le=3.0)
    screen: float = Field(default=0.14, ge=0.0, le=0.5)
    texture: float = Field(default=0.055, ge=0.0, le=0.3)
    accent_strength: float = Field(default=0.52, ge=0.0, le=1.0)
    misregister: Points = Field(default=1.5, ge=0.0, le=12.0)
    scan_pitch: Points = Field(default=4.5, ge=1.0, le=40.0)


class ArchivePrint(Effect):
    """Map photography into a reproducible three-ink future-archive print."""

    kind: ClassVar[EffectKind] = EffectKind.RASTER
    param_schema: ClassVar[type[BaseModel]] = ArchivePrintParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Stays inside the node — declares no outward paint (honest zero expansion)."""
        return Insets()

    def apply(self, ctx: object) -> object:
        """Return a three-ink print simulation while preserving the source alpha exactly."""
        assert isinstance(ctx, RasterContext)
        params = ctx.params
        assert isinstance(params, ArchivePrintParams)

        rgba = image_to_rgba(ctx.image)
        h, w = rgba.shape[:2]
        rgb = rgba[..., :3].astype(np.float32) / 255.0
        alpha = rgba[..., 3:4]

        # Work in luminance so skin, cloth, ceramics, and backgrounds share one editorial ink
        # language.  The slight toe/shoulder compression keeps both faces and highlights legible.
        luminance = (
            rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
        )
        tone = np.clip((luminance - 0.5) * params.contrast + 0.5, 0.0, 1.0)

        yy, xx = np.indices((h, w), dtype=np.int32)
        screen_cell = ((xx * 3 + yy * 5) % 17).astype(np.float32) / 16.0 - 0.5
        screened = np.clip(tone + screen_cell * params.screen, 0.0, 1.0)
        steps = float(params.levels - 1)
        quantized = np.floor(screened * steps + 0.5) / steps

        shadow = np.asarray(params.shadow[:3], dtype=np.float32)
        paper = np.asarray(params.paper[:3], dtype=np.float32)
        accent = np.asarray(params.accent[:3], dtype=np.float32)
        printed = shadow + (paper - shadow) * quantized[..., None]

        # A print-like registration fringe follows real source edges and cool chroma instead of
        # shifting the whole image.  Padding avoids the wraparound seam produced by np.roll.
        padded = np.pad(luminance, ((1, 1), (1, 1)), mode="edge")
        edge_x = np.abs(padded[1:-1, 2:] - padded[1:-1, :-2])
        edge_y = np.abs(padded[2:, 1:-1] - padded[:-2, 1:-1])
        edge = np.clip((edge_x + edge_y) * 3.8, 0.0, 1.0)
        cool = np.clip((rgb[..., 2] - rgb[..., 0]) * 1.7, 0.0, 1.0)
        accent_mask = np.maximum(edge, cool * 0.65)
        shift_px = int(round(params.misregister * ctx.dpi / 72.0))
        if shift_px > 0:
            shifted = np.zeros_like(accent_mask)
            shifted[:, shift_px:] = accent_mask[:, : w - shift_px]
            accent_mask = shifted
        accent_mix = np.clip(accent_mask * params.accent_strength, 0.0, 0.82)
        printed = printed * (1.0 - accent_mix[..., None]) + accent * accent_mix[..., None]

        # Fine horizontal scan bands bridge archival printing and computational imaging without
        # overpowering the subject.  Seeded noise supplies reproducible paper fibres/speckle.
        pitch_px = max(1, int(round(params.scan_pitch * ctx.dpi / 72.0)))
        band = ((yy % pitch_px) == 0).astype(np.float32) * 0.055
        printed *= 1.0 - band[..., None]
        grain = ctx.rng.normal(0.0, params.texture, size=(h, w, 1)).astype(np.float32)
        printed = np.clip(printed + grain, 0.0, 1.0)

        out = np.empty_like(rgba)
        out[..., :3] = np.rint(printed * 255.0).astype(np.uint8)
        out[..., 3:4] = alpha
        return rgba_to_image(out)

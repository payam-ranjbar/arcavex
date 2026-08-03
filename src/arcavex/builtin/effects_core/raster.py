"""Raster-category effects: blur, grain, noise, ink-bleed, halftone, channel-offset,
edge-wear, and palette-map.

Each takes the node's element raster (RGBA straight-alpha, covering the expanded paint region)
and returns a new raster of the same pixel size. Skia-native effects (blur, ink-bleed,
halftone) go through the surface pool; grain/noise/edge-wear/channel-offset/palette-map are
numpy passes on the pixel array. Anything random draws from ``ctx.rng`` only, so a fixed seed
gives byte-identical output (spec §3.2, §4.4).

``bounds_expansion`` is mandatory and honest: blur declares its spread, the rest declare zero.
"""

from __future__ import annotations

import struct
from typing import ClassVar

import numpy as np
import skia  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from arcavex.builtin.effects_core.context import (
    LUMA,
    RasterContext,
    image_to_rgba,
    render_to_pool,
    rgba_to_image,
)
from arcavex.builtin.effects_core.params import (
    GAUSSIAN_VISIBLE_SIGMAS,
    Points,
    RGBAColor,
)
from arcavex.kernel.contracts.spi import Effect
from arcavex.kernel.contracts.types import EffectKind
from arcavex.kernel.ir.units import Insets
from arcavex.kernel.ir.units import pt_to_px as _pt_to_px


class _RasterEffect(Effect):
    """Base for raster effects; most declare no bounds growth."""

    kind: ClassVar[EffectKind] = EffectKind.RASTER

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Default: a raster effect that stays inside the node paints no wider."""
        return Insets()


# --------------------------------------------------------------------------------- blur
class BlurParams(BaseModel):
    """Gaussian blur with a point ``radius`` (sigma)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    radius: Points = Field(default=4.0, ge=0.0)


class Blur(_RasterEffect):
    """Gaussian blur via a Skia image filter; declares its spread so it is not clipped."""

    param_schema: ClassVar[type[BaseModel]] = BlurParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Grow the paint region by the blur's visible spread on every side."""
        assert isinstance(params, BlurParams)
        pad = params.radius * GAUSSIAN_VISIBLE_SIGMAS
        return Insets(pad, pad, pad, pad)

    def apply(self, ctx: object) -> skia.Image:
        """Return the blurred raster."""
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, BlurParams)
        sigma = _pt_to_px(p.radius, ctx.dpi)
        image = ctx.image
        image_filter = skia.ImageFilters.Blur(sigma, sigma)

        def draw(canvas: skia.Canvas) -> None:
            paint = skia.Paint()
            paint.setImageFilter(image_filter)
            canvas.drawImage(image, 0, 0, skia.SamplingOptions(), paint)

        return render_to_pool(ctx.pool, image.width(), image.height(), draw)


# --------------------------------------------------------------------------------- grain
class GrainParams(BaseModel):
    """Monochrome film grain: per-pixel luminance jitter of amplitude ``amount``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: float = Field(default=0.08, ge=0.0, le=1.0)


class Grain(_RasterEffect):
    """Seeded monochrome grain: one shared noise field jitters RGB (alpha is left untouched)."""

    param_schema: ClassVar[type[BaseModel]] = GrainParams

    def apply(self, ctx: object) -> skia.Image:
        """Return the grained raster (RGB jittered by one shared noise field, alpha kept)."""
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, GrainParams)
        rgba = image_to_rgba(ctx.image).astype(np.int16)
        h, w = rgba.shape[:2]
        noise = ctx.rng.normal(0.0, p.amount * 255.0, size=(h, w, 1))
        rgba[..., :3] = np.clip(rgba[..., :3] + noise, 0, 255)
        return rgba_to_image(rgba.astype(np.uint8))


# --------------------------------------------------------------------------------- noise
class NoiseParams(BaseModel):
    """Coloured RGB noise mixed in at strength ``amount``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: float = Field(default=0.12, ge=0.0, le=1.0)


class Noise(_RasterEffect):
    """Seeded per-channel colour noise."""

    param_schema: ClassVar[type[BaseModel]] = NoiseParams

    def apply(self, ctx: object) -> skia.Image:
        """Return the raster with independent per-channel noise added to RGB (alpha untouched)."""
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, NoiseParams)
        rgba = image_to_rgba(ctx.image).astype(np.int16)
        h, w = rgba.shape[:2]
        noise = ctx.rng.normal(0.0, p.amount * 255.0, size=(h, w, 3))
        rgba[..., :3] = np.clip(rgba[..., :3] + noise, 0, 255)
        return rgba_to_image(rgba.astype(np.uint8))


# ----------------------------------------------------------------------------- ink-bleed
class InkBleedParams(BaseModel):
    """Grow dark ink into lighter areas by a point ``radius`` (grey erosion of the ink)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    radius: Points = Field(default=1.5, ge=0.0)


def _box_min(a: np.ndarray, r: int) -> np.ndarray:
    """Separable edge-clamped box minimum of radius ``r`` (a morphological grey erosion).

    Grows the darker value outward by ``r`` pixels on each axis, clamping at the array edge (no
    wrap), so dark ink spreads into lighter neighbours deterministically.
    """
    acc = a
    for d in range(1, r + 1):
        left = np.empty_like(a)
        left[:, d:] = a[:, :-d]
        left[:, :d] = a[:, :1]
        right = np.empty_like(a)
        right[:, :-d] = a[:, d:]
        right[:, -d:] = a[:, -1:]
        acc = np.minimum(np.minimum(acc, left), right)
    horizontal = acc
    for d in range(1, r + 1):
        up = np.empty_like(horizontal)
        up[d:, :] = horizontal[:-d, :]
        up[:d, :] = horizontal[:1, :]
        down = np.empty_like(horizontal)
        down[:-d, :] = horizontal[d:, :]
        down[-d:, :] = horizontal[-1:, :]
        acc = np.minimum(np.minimum(acc, up), down)
    return acc


class InkBleed(_RasterEffect):
    """Spread dark ink into lighter opaque areas (a grey erosion), mimicking wet-ink spread.

    Only opaque pixels feed the erosion — the cleared padding never darkens ink at the edges —
    and alpha is left untouched, so the effect thickens ink without eroding the node silhouette.
    It grows ink *inward* among opaque content and so declares no bounds expansion.
    """

    param_schema: ClassVar[type[BaseModel]] = InkBleedParams

    def apply(self, ctx: object) -> skia.Image:
        """Return the raster with dark ink grown into lighter opaque neighbours."""
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, InkBleedParams)
        r = max(1, int(round(_pt_to_px(p.radius, ctx.dpi))))
        rgba = image_to_rgba(ctx.image)
        rgb = rgba[..., :3].astype(np.int16)
        opaque = rgba[..., 3] > 0
        # Transparent pixels are treated as maximally light so they never darken a neighbour,
        # so ink bleeds only from real opaque content, not from the cleared surface padding.
        work = np.where(opaque[..., None], rgb, 255)
        bled = _box_min(work, r)
        out = rgba.copy()
        out[..., :3] = np.where(opaque[..., None], bled, rgb).astype(np.uint8)
        return rgba_to_image(out)


# -------------------------------------------------------------------------------- halftone
# Ink is passed as three scalar float uniforms (not a float3) so the CPU-side uniform buffer
# is tightly packed 4-byte floats — no vec3 16-byte alignment to second-guess.
_HALFTONE_SKSL = """
uniform shader src;
uniform float pitch;
uniform float angle;
uniform float ink_r;
uniform float ink_g;
uniform float ink_b;
half4 main(float2 p) {
    float c = cos(angle), s = sin(angle);
    float2 q = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    float2 cell = (floor(q / pitch) + 0.5) * pitch;
    float2 center = float2(c * cell.x + s * cell.y, -s * cell.x + c * cell.y);
    half4 sc = src.eval(center);
    float lum = 0.2126 * sc.r + 0.7152 * sc.g + 0.0722 * sc.b;
    float radius = (pitch * 0.5) * sqrt(max(0.0, 1.0 - lum));
    float d = length(q - cell);
    float coverage = smoothstep(radius + 0.75, radius - 0.75, d) * sc.a;
    return half4(half3(ink_r, ink_g, ink_b) * coverage, coverage);
}
"""


class HalftoneParams(BaseModel):
    """Rotated dot screen: ``pitch`` cell size (points), ``angle`` degrees, ``ink`` colour.

    Dot area grows with source darkness — the classic amplitude-modulated halftone. Rendered
    in SkSL (spec Phase 3 exit criterion), pitch converted points→pixels so the screen is
    DPI-stable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pitch: Points = Field(default=6.0, gt=0.0)
    angle: float = Field(default=15.0)
    ink: RGBAColor = Field(default=(0.0, 0.0, 0.0, 1.0))


class Halftone(_RasterEffect):
    """SkSL amplitude-modulated dot-screen halftone on luminance."""

    param_schema: ClassVar[type[BaseModel]] = HalftoneParams
    _effect: ClassVar[skia.RuntimeEffect] = skia.RuntimeEffect.MakeForShader(_HALFTONE_SKSL)

    def apply(self, ctx: object) -> skia.Image:
        """Return the halftoned raster (transparent where the source is transparent)."""
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, HalftoneParams)
        image = ctx.image
        pitch_px = max(1.5, _pt_to_px(p.pitch, ctx.dpi))
        angle_rad = np.radians(p.angle)
        child = image.makeShader(
            skia.TileMode.kClamp, skia.TileMode.kClamp, skia.SamplingOptions()
        )
        uniforms = skia.Data.MakeWithCopy(
            struct.pack("<fffff", pitch_px, float(angle_rad), p.ink[0], p.ink[1], p.ink[2])
        )
        shader = self._effect.makeShader(uniforms, child, 1)

        def draw(canvas: skia.Canvas) -> None:
            paint = skia.Paint()
            paint.setShader(shader)
            canvas.drawRect(skia.Rect.MakeWH(image.width(), image.height()), paint)

        return render_to_pool(ctx.pool, image.width(), image.height(), draw)


# ------------------------------------------------------------------------- channel-offset
class ChannelOffsetParams(BaseModel):
    """Chromatic-aberration split: shift red and blue apart by ``distance`` points."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    distance: Points = Field(default=2.0)
    angle: float = Field(default=0.0)


class ChannelOffset(_RasterEffect):
    """Displace the red and blue channels in opposite directions (RGB split)."""

    param_schema: ClassVar[type[BaseModel]] = ChannelOffsetParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """The split can push a channel up to ``distance`` outward."""
        assert isinstance(params, ChannelOffsetParams)
        d = abs(params.distance)
        return Insets(d, d, d, d)

    def apply(self, ctx: object) -> skia.Image:
        """Return the raster with red/blue shifted apart by whole-pixel offsets."""
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, ChannelOffsetParams)
        rgba = image_to_rgba(ctx.image)
        dpx = _pt_to_px(p.distance, ctx.dpi)
        rad = np.radians(p.angle)
        dx = int(round(dpx * np.cos(rad)))
        dy = int(round(dpx * np.sin(rad)))
        out = rgba.copy()
        out[..., 0] = np.roll(rgba[..., 0], (dy, dx), axis=(0, 1))
        out[..., 2] = np.roll(rgba[..., 2], (-dy, -dx), axis=(0, 1))
        return rgba_to_image(out)


# ----------------------------------------------------------------------------- edge-wear
class EdgeWearParams(BaseModel):
    """Distress edges: erode alpha at high-contrast borders by seeded speckle at ``amount``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: float = Field(default=0.3, ge=0.0, le=1.0)


class EdgeWear(_RasterEffect):
    """Seeded alpha speckling concentrated on edges, for a worn print look."""

    param_schema: ClassVar[type[BaseModel]] = EdgeWearParams

    def apply(self, ctx: object) -> skia.Image:
        """Return the raster with edge pixels randomly knocked out."""
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, EdgeWearParams)
        rgba = image_to_rgba(ctx.image)
        alpha = rgba[..., 3].astype(np.float32) / 255.0
        # Edge strength = local alpha gradient magnitude (where content meets transparency).
        gy = np.abs(np.diff(alpha, axis=0, prepend=alpha[:1, :]))
        gx = np.abs(np.diff(alpha, axis=1, prepend=alpha[:, :1]))
        edge = np.clip(gx + gy, 0.0, 1.0)
        speckle = ctx.rng.random(size=alpha.shape).astype(np.float32)
        knock = (speckle < edge * p.amount)
        out = rgba.copy()
        out[..., 3] = np.where(knock, 0, rgba[..., 3])
        return rgba_to_image(out)


# --------------------------------------------------------------------------- palette-map
class PaletteMapParams(BaseModel):
    """Map each pixel's luminance to the nearest of an ordered ``colors`` palette.

    Luminance→colour is not a per-channel operation, so palette-map is a raster pass, not a
    fusable color transform (documented deviation from the spec's "color" grouping). Alpha is
    preserved, so it recolours content without touching its silhouette.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    colors: tuple[RGBAColor, ...] = Field(min_length=2)


class PaletteMap(_RasterEffect):
    """Quantize by luminance to a fixed ordered palette."""

    param_schema: ClassVar[type[BaseModel]] = PaletteMapParams

    def apply(self, ctx: object) -> skia.Image:
        """Return the palette-mapped raster."""
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, PaletteMapParams)
        rgba = image_to_rgba(ctx.image)
        rgb = rgba[..., :3].astype(np.float32) / 255.0
        lum = rgb @ np.array(LUMA, dtype=np.float32)
        n = len(p.colors)
        bucket = np.clip((lum * n).astype(np.int32), 0, n - 1)
        palette = np.array(
            [[c[0] * 255, c[1] * 255, c[2] * 255] for c in p.colors], dtype=np.float32
        )
        out = rgba.copy()
        out[..., :3] = palette[bucket].astype(np.uint8)
        return rgba_to_image(out)

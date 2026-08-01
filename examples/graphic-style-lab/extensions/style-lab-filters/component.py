"""Four deterministic raster treatments for the Arcavex Graphic Style Lab.

The generated source photographs in this example are intentionally neutral.  These effects own
the visible print, copy, cinema, and risograph character so the final pieces prove that Arcavex is
doing the styling rather than receiving pre-stylized pixels.
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


def _rgb(color: RGBAColor) -> np.ndarray:
    return np.asarray(color[:3], dtype=np.float32)


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _contrast(tone: np.ndarray, amount: float) -> np.ndarray:
    return np.clip((tone - 0.5) * amount + 0.5, 0.0, 1.0)


def _edge_map(tone: np.ndarray) -> np.ndarray:
    padded = np.pad(tone, ((1, 1), (1, 1)), mode="edge")
    gx = np.abs(padded[1:-1, 2:] - padded[1:-1, :-2])
    gy = np.abs(padded[2:, 1:-1] - padded[:-2, 1:-1])
    return np.clip((gx + gy) * 3.25, 0.0, 1.0)


def _shift_zero(field: np.ndarray, dx: int, dy: int = 0) -> np.ndarray:
    out = np.zeros_like(field)
    h, w = field.shape[:2]
    src_x0, src_x1 = max(0, -dx), min(w, w - dx)
    src_y0, src_y1 = max(0, -dy), min(h, h - dy)
    dst_x0, dst_x1 = max(0, dx), min(w, w + dx)
    dst_y0, dst_y1 = max(0, dy), min(h, h + dy)
    if src_x1 > src_x0 and src_y1 > src_y0:
        out[dst_y0:dst_y1, dst_x0:dst_x1] = field[src_y0:src_y1, src_x0:src_x1]
    return out


def _soft_blur(field: np.ndarray, passes: int = 4) -> np.ndarray:
    blurred = field.astype(np.float32, copy=True)
    for _ in range(passes):
        p = np.pad(blurred, ((1, 1), (1, 1)), mode="edge")
        blurred = (
            p[1:-1, 1:-1] * 4.0
            + p[:-2, 1:-1]
            + p[2:, 1:-1]
            + p[1:-1, :-2]
            + p[1:-1, 2:]
        ) / 8.0
    return blurred


class _ContainedRasterEffect(Effect):
    kind: ClassVar[EffectKind] = EffectKind.RASTER

    def bounds_expansion(self, params: BaseModel) -> Insets:
        return Insets()


class SwissCutParams(BaseModel):
    """Clean limited-ink portrait with a registered signal color."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    ink: RGBAColor = "#111111"
    paper: RGBAColor = "#F3F0E8"
    signal: RGBAColor = "#FF3B30"
    levels: int = Field(default=4, ge=2, le=8)
    contrast: float = Field(default=1.32, ge=0.25, le=3.0)
    edge_accent: float = Field(default=0.72, ge=0.0, le=1.0)
    register_shift: Points = Field(default=2.0, ge=0.0, le=16.0)


class SwissCut(_ContainedRasterEffect):
    """Turn neutral photography into a crisp three-ink Swiss editorial cut."""

    param_schema: ClassVar[type[BaseModel]] = SwissCutParams

    def apply(self, ctx: object) -> object:
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, SwissCutParams)
        rgba = image_to_rgba(ctx.image)
        rgb = rgba[..., :3].astype(np.float32) / 255.0
        tone = _contrast(_luma(rgb), p.contrast)
        steps = float(p.levels - 1)
        quantized = np.floor(tone * steps + 0.5) / steps
        printed = _rgb(p.ink) + (_rgb(p.paper) - _rgb(p.ink)) * quantized[..., None]

        edge = _edge_map(tone)
        shift = int(round(p.register_shift * ctx.dpi / 72.0))
        registered = _shift_zero(edge, shift, -max(0, shift // 2))
        yy, xx = np.indices(tone.shape, dtype=np.int32)
        clean_screen = (((xx + yy * 2) % 31) < 3).astype(np.float32)
        midtone = np.clip(1.0 - np.abs(tone - 0.5) * 3.1, 0.0, 1.0)
        accent_mask = np.clip(
            registered * p.edge_accent + clean_screen * midtone * 0.16,
            0.0,
            0.82,
        )
        printed = printed * (1.0 - accent_mask[..., None]) + _rgb(p.signal) * accent_mask[..., None]

        out = rgba.copy()
        out[..., :3] = np.rint(np.clip(printed, 0.0, 1.0) * 255.0).astype(np.uint8)
        return rgba_to_image(out)


class XeroxPulseParams(BaseModel):
    """High-contrast photocopy with deterministic streak, dropout, and slice jitter."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    ink: RGBAColor = "#111111"
    paper: RGBAColor = "#F4F0E6"
    threshold: float = Field(default=0.54, ge=0.05, le=0.95)
    contrast: float = Field(default=1.7, ge=0.25, le=4.0)
    grit: float = Field(default=0.13, ge=0.0, le=0.5)
    dropout: float = Field(default=0.025, ge=0.0, le=0.25)
    slice_pitch: Points = Field(default=28.0, ge=8.0, le=120.0)
    slice_shift: Points = Field(default=3.0, ge=0.0, le=18.0)


class XeroxPulse(_ContainedRasterEffect):
    """Build an aggressive but legible black-and-paper copier treatment."""

    param_schema: ClassVar[type[BaseModel]] = XeroxPulseParams

    def apply(self, ctx: object) -> object:
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, XeroxPulseParams)
        rgba = image_to_rgba(ctx.image)
        tone = _contrast(_luma(rgba[..., :3].astype(np.float32) / 255.0), p.contrast)
        h, w = tone.shape
        yy, xx = np.indices((h, w), dtype=np.int32)
        coarse = ctx.rng.normal(0.0, p.grit, size=(h, w)).astype(np.float32)
        scan = (((yy % 9) == 0).astype(np.float32) - 0.2) * 0.055
        ink_mask = tone + coarse + scan < p.threshold

        pitch = max(8, int(round(p.slice_pitch * ctx.dpi / 72.0)))
        shift = int(round(p.slice_shift * ctx.dpi / 72.0))
        sliced = ink_mask.copy()
        for band, y0 in enumerate(range(0, h, pitch)):
            if band % 3 == 1 and shift:
                y1 = min(h, y0 + max(2, pitch // 5))
                amount = shift if band % 2 else -shift
                sliced[y0:y1] = _shift_zero(sliced[y0:y1], amount)

        dropout = ctx.rng.random((h, w)) < p.dropout
        dust = ctx.rng.random((h, w)) < p.dropout * 0.34
        ink_mask = np.logical_or(np.logical_and(sliced, ~dropout), dust)
        printed = np.where(ink_mask[..., None], _rgb(p.ink), _rgb(p.paper))
        out = rgba.copy()
        out[..., :3] = np.rint(printed * 255.0).astype(np.uint8)
        return rgba_to_image(out)


class CinemaEmulsionParams(BaseModel):
    """Split-tone cinema emulsion with real highlight-derived halation."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    shadow: RGBAColor = "#041C27"
    mid: RGBAColor = "#294650"
    highlight: RGBAColor = "#F4B56A"
    contrast: float = Field(default=1.22, ge=0.25, le=3.0)
    source_color: float = Field(default=0.14, ge=0.0, le=0.6)
    halation: float = Field(default=0.24, ge=0.0, le=0.8)
    vignette: float = Field(default=0.3, ge=0.0, le=0.8)
    grain: float = Field(default=0.025, ge=0.0, le=0.25)


class CinemaEmulsion(_ContainedRasterEffect):
    """Apply a cinematic curve, shadow/highlight split, halation, vignette, and grain."""

    param_schema: ClassVar[type[BaseModel]] = CinemaEmulsionParams

    def apply(self, ctx: object) -> object:
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, CinemaEmulsionParams)
        rgba = image_to_rgba(ctx.image)
        rgb = rgba[..., :3].astype(np.float32) / 255.0
        tone = _contrast(_luma(rgb), p.contrast)

        low_t = np.clip(tone * 2.0, 0.0, 1.0)[..., None]
        high_t = np.clip((tone - 0.5) * 2.0, 0.0, 1.0)[..., None]
        low = _rgb(p.shadow) + (_rgb(p.mid) - _rgb(p.shadow)) * low_t
        high = _rgb(p.mid) + (_rgb(p.highlight) - _rgb(p.mid)) * high_t
        graded = np.where((tone < 0.5)[..., None], low, high)
        graded = graded * (1.0 - p.source_color) + rgb * p.source_color

        highlights = np.clip((tone - 0.7) / 0.3, 0.0, 1.0)
        halo = _soft_blur(highlights, passes=6)
        warm = np.asarray([1.0, 0.24, 0.055], dtype=np.float32)
        graded += halo[..., None] * warm * p.halation

        h, w = tone.shape
        yy, xx = np.indices((h, w), dtype=np.float32)
        nx = (xx - (w - 1) / 2.0) / max(1.0, w / 2.0)
        ny = (yy - (h - 1) / 2.0) / max(1.0, h / 2.0)
        vignette = np.clip(1.0 - (nx * nx + ny * ny) * p.vignette, 0.48, 1.0)
        graded *= vignette[..., None]
        noise = ctx.rng.normal(0.0, p.grain, size=(h, w, 1)).astype(np.float32)
        graded = np.clip(graded + noise, 0.0, 1.0)

        out = rgba.copy()
        out[..., :3] = np.rint(graded * 255.0).astype(np.uint8)
        return rgba_to_image(out)


class RisoRegisterParams(BaseModel):
    """Four-ink ordered screen with deliberately imperfect registration."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    dark: RGBAColor = "#1B1838"
    blue: RGBAColor = "#244CFF"
    red: RGBAColor = "#FF4B45"
    paper: RGBAColor = "#F7E9C8"
    contrast: float = Field(default=1.12, ge=0.25, le=3.0)
    dither: float = Field(default=0.36, ge=0.0, le=1.0)
    register_shift: Points = Field(default=2.2, ge=0.0, le=16.0)
    texture: float = Field(default=0.025, ge=0.0, le=0.2)


class RisoRegister(_ContainedRasterEffect):
    """Map a neutral product photo into a vivid four-ink risograph print."""

    param_schema: ClassVar[type[BaseModel]] = RisoRegisterParams

    def apply(self, ctx: object) -> object:
        assert isinstance(ctx, RasterContext)
        p = ctx.params
        assert isinstance(p, RisoRegisterParams)
        rgba = image_to_rgba(ctx.image)
        rgb = rgba[..., :3].astype(np.float32) / 255.0
        tone = _contrast(_luma(rgb), p.contrast)
        h, w = tone.shape
        yy, xx = np.indices((h, w), dtype=np.int32)
        bayer = np.asarray(
            [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
            dtype=np.float32,
        ) / 15.0 - 0.5
        ordered = bayer[yy % 4, xx % 4] * p.dither
        bucket = np.clip(np.floor((tone + ordered * 0.26) * 4.0), 0, 3).astype(np.int32)
        palette = np.stack([_rgb(p.dark), _rgb(p.blue), _rgb(p.red), _rgb(p.paper)])
        printed = palette[bucket]

        edge = _edge_map(tone)
        shift = int(round(p.register_shift * ctx.dpi / 72.0))
        blue_plate = _shift_zero(edge, -shift, 0) * 0.42
        red_plate = _shift_zero(edge, shift, max(0, shift // 2)) * 0.42
        printed = printed * (1.0 - blue_plate[..., None]) + _rgb(p.blue) * blue_plate[..., None]
        printed = printed * (1.0 - red_plate[..., None]) + _rgb(p.red) * red_plate[..., None]
        paper_fibre = ctx.rng.normal(0.0, p.texture, size=(h, w, 1)).astype(np.float32)
        printed = np.clip(printed + paper_fibre, 0.0, 1.0)

        out = rgba.copy()
        out[..., :3] = np.rint(printed * 255.0).astype(np.uint8)
        return rgba_to_image(out)

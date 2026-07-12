"""Skia renderer backend v0.

Renders a :class:`LayoutDocument` onto a raster surface sized in device pixels. The canvas
is scaled by ``dpi/72`` so all drawing happens in point coordinates, keeping geometry and
text measurement in the same unit. Traversal is document order with ``z`` already applied by
the layout solver. Randomness, wall-clock, and system fonts are never consulted, so repeated
renders are byte-identical.
"""

from __future__ import annotations

from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.kernel.contracts.spi import RendererBackend
from arcavex.kernel.contracts.types import MeasureRequest, RenderOptions, Surface
from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.kernel.ir.models import (
    LayoutDocument,
    LayoutNode,
    ResolvedImage,
    ResolvedShape,
    ResolvedText,
)
from arcavex.kernel.ir.units import Rect
from arcavex.services.text.service import TextService


class SkiaBackend(RendererBackend):
    """Renders laid-out documents to Skia raster surfaces."""

    name: ClassVar[str] = "skia"

    def __init__(self, text_service: TextService) -> None:
        """Bind the backend to the shared text service used for painting text."""
        self._text = text_service

    def render(self, doc: LayoutDocument, opts: RenderOptions) -> Surface:
        """Render ``doc`` and return the raster surface."""
        dpi = opts.dpi or doc.canvas.dpi
        width_px = max(1, round(doc.canvas.width_pt * dpi / 72.0))
        height_px = max(1, round(doc.canvas.height_pt * dpi / 72.0))
        surface = skia.Surface(width_px, height_px)
        canvas = surface.getCanvas()
        canvas.clear(skia.Color4f(0, 0, 0, 0))
        canvas.save()
        canvas.scale(dpi / 72.0, dpi / 72.0)
        self._draw_node(canvas, doc.root)
        canvas.restore()
        return surface  # type: ignore[return-value]

    # ------------------------------------------------------------------ internals
    def _draw_node(self, canvas: object, node: LayoutNode) -> None:
        if not _visible(node):
            return
        content = node.resolved_content
        if isinstance(content, ResolvedShape):
            self._draw_shape(canvas, node.bounds, content, node.opacity)
        elif isinstance(content, ResolvedText):
            self._draw_text(canvas, node.bounds, content)
        elif isinstance(content, ResolvedImage):
            self._draw_image(canvas, node.bounds, content, node.opacity)

        if node.kind == "group" and node.children:
            did_clip = False
            if node.clip:
                canvas.save()  # type: ignore[attr-defined]
                canvas.clipRect(_skrect(node.bounds))  # type: ignore[attr-defined]
                did_clip = True
            for child in node.children:
                self._draw_node(canvas, child)
            if did_clip:
                canvas.restore()  # type: ignore[attr-defined]

    def _draw_shape(
        self, canvas: object, bounds: Rect, shape: ResolvedShape, opacity: float
    ) -> None:
        rect = _skrect(bounds)
        if shape.fill is not None:
            paint = _fill_paint(shape.fill, opacity)
            self._paint_shape(canvas, shape, rect, bounds, paint)
        if shape.stroke is not None and shape.stroke_width_pt > 0:
            paint = _stroke_paint(shape.stroke, shape.stroke_width_pt, opacity)
            self._paint_shape(canvas, shape, rect, bounds, paint)

    def _paint_shape(
        self, canvas: object, shape: ResolvedShape, rect: object, bounds: Rect, paint: object
    ) -> None:
        if shape.shape == "circle":
            radius = min(bounds.w, bounds.h) / 2.0
            canvas.drawCircle(bounds.center_x, bounds.center_y, radius, paint)  # type: ignore[attr-defined]
        elif shape.shape == "rrect" or shape.corner_radius_pt > 0:
            r = shape.corner_radius_pt
            canvas.drawRoundRect(rect, r, r, paint)  # type: ignore[attr-defined]
        else:
            canvas.drawRect(rect, paint)  # type: ignore[attr-defined]

    def _draw_text(self, canvas: object, bounds: Rect, text: ResolvedText) -> None:
        req = MeasureRequest(
            text=text.text,
            font_families=text.font_families,
            font_size_pt=text.font_size_pt,
            font_weight=text.font_weight,
            italic=text.italic,
            letter_spacing_pt=text.letter_spacing_pt,
            line_height=text.line_height,
            direction=text.direction,
            max_width_pt=bounds.w,
        )
        self._text.paint(
            canvas,
            req,
            bounds.x,
            bounds.y,
            bounds.w,
            color=text.color,
            align=text.align,
        )

    def _draw_image(
        self, canvas: object, bounds: Rect, image_spec: ResolvedImage, opacity: float
    ) -> None:
        # Missing assets are caught at compile time (ARC-AST-001) so validate reports them.
        # A file that exists but cannot be decoded still reaches here; skia raises
        # ValueError/RuntimeError rather than returning None, so guard the decode and
        # surface a located asset diagnostic (exit 3) instead of an ARC-INT-999 leak.
        try:
            image = skia.Image.open(image_spec.asset_path)
        except (ValueError, RuntimeError) as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-AST-002",
                    f"Could not decode image asset: {image_spec.asset_path}",
                    hint="Check that the file is a supported, undamaged image format.",
                )
            ) from exc
        if image is None:
            raise DiagnosticError(
                diagnostic(
                    "ARC-AST-002",
                    f"Could not decode image asset: {image_spec.asset_path}",
                    hint="Check that the file is a supported, undamaged image format.",
                )
            )
        iw, ih = float(image.width()), float(image.height())
        dst = _skrect(bounds)
        paint = skia.Paint()
        paint.setAntiAlias(True)
        if opacity < 1.0:
            paint.setAlphaf(opacity)
        sampling = skia.SamplingOptions(skia.FilterMode.kLinear)
        canvas.save()  # type: ignore[attr-defined]
        canvas.clipRect(dst)  # type: ignore[attr-defined]
        if image_spec.fit == "fill":
            target = dst
        else:
            if image_spec.fit == "cover":
                scale = max(bounds.w / iw, bounds.h / ih)
            else:  # contain
                scale = min(bounds.w / iw, bounds.h / ih)
            dw, dh = iw * scale, ih * scale
            dx = bounds.x + (bounds.w - dw) / 2.0
            dy = bounds.y + (bounds.h - dh) / 2.0
            target = skia.Rect.MakeXYWH(dx, dy, dw, dh)
        canvas.drawImageRect(image, target, sampling, paint)  # type: ignore[attr-defined]
        canvas.restore()  # type: ignore[attr-defined]


def _visible(node: LayoutNode) -> bool:
    # Explicit visibility state carried on the layout node wins; a fully transparent node
    # is also skipped as a harmless optimization.
    return node.visible and node.opacity > 0.0


def _skrect(bounds: Rect) -> object:
    return skia.Rect.MakeXYWH(bounds.x, bounds.y, bounds.w, bounds.h)


def _fill_paint(color: tuple[float, float, float, float], opacity: float) -> object:
    paint = skia.Paint()
    paint.setAntiAlias(True)
    paint.setStyle(skia.Paint.kFill_Style)
    paint.setColor4f(skia.Color4f(color[0], color[1], color[2], color[3] * opacity))
    return paint


def _stroke_paint(
    color: tuple[float, float, float, float], width_pt: float, opacity: float
) -> object:
    paint = skia.Paint()
    paint.setAntiAlias(True)
    paint.setStyle(skia.Paint.kStroke_Style)
    paint.setStrokeWidth(width_pt)
    paint.setColor4f(skia.Color4f(color[0], color[1], color[2], color[3] * opacity))
    return paint

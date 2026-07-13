"""Skia renderer backend.

Renders a :class:`LayoutDocument` onto a raster surface sized in device pixels. The canvas
is scaled by ``dpi/72`` so all drawing happens in point coordinates, keeping geometry and
text measurement in the same unit. Traversal is document order with ``z`` already applied by
the layout solver. A node may rotate about its origin, clip its subtree to a mask path, and a
text node may clip to its box; ``--debug`` overlays node bounds, ids, baselines, and the
safe-area margin deterministically without touching the non-debug scene. Randomness,
wall-clock, and system fonts are never consulted, so repeated renders are byte-identical.
"""

from __future__ import annotations

from typing import Any, ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.kernel.contracts.spi import MaskGenerator, RendererBackend
from arcavex.kernel.contracts.types import MeasureRequest, RenderOptions, Surface
from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.kernel.ir.models import (
    LayoutDocument,
    LayoutNode,
    MaskSpec,
    ResolvedImage,
    ResolvedShape,
    ResolvedText,
    SourceRef,
)
from arcavex.kernel.ir.units import Rect
from arcavex.services.text.service import TextService

# Deterministic debug-overlay palette, indexed by node kind.
_DEBUG_COLORS: dict[str, tuple[float, float, float, float]] = {
    "group": (0.20, 0.60, 1.00, 1.0),
    "text": (1.00, 0.30, 0.45, 1.0),
    "image": (0.20, 0.85, 0.55, 1.0),
    "shape": (1.00, 0.75, 0.20, 1.0),
    "path": (0.75, 0.45, 1.00, 1.0),
}
_DEBUG_SAFE_AREA = (0.55, 0.55, 0.60, 1.0)
_SAFE_MARGIN_FRAC = 0.05
_DEBUG_LABEL_PT = 9.0


class SkiaBackend(RendererBackend):
    """Renders laid-out documents to Skia raster surfaces."""

    name: ClassVar[str] = "skia"

    def __init__(
        self, text_service: TextService, masks: dict[str, MaskGenerator] | None = None
    ) -> None:
        """Bind the backend to the shared text service and the mask-generator registry."""
        self._text = text_service
        self._masks = masks or {}

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
        if opts.debug:
            self._draw_debug(canvas, doc)
        canvas.restore()
        return surface  # type: ignore[return-value]

    # ------------------------------------------------------------------ internals
    def _draw_node(self, canvas: object, node: LayoutNode) -> None:
        if not _visible(node):
            return
        saves = 0
        if node.rotate_deg and node.rotate_origin is not None:
            canvas.save()  # type: ignore[attr-defined]
            canvas.rotate(node.rotate_deg, node.rotate_origin[0], node.rotate_origin[1])  # type: ignore[attr-defined]
            saves += 1
        if node.mask is not None:
            path = self._mask_path(node.mask, node.bounds, node.source)
            if path is not None:
                canvas.save()  # type: ignore[attr-defined]
                canvas.clipPath(path, skia.ClipOp.kIntersect, True)  # type: ignore[attr-defined]
                saves += 1

        content = node.resolved_content
        if isinstance(content, ResolvedShape):
            self._draw_shape(canvas, node.bounds, content, node.opacity)
        elif isinstance(content, ResolvedText):
            self._draw_text(canvas, node.bounds, content)
        elif isinstance(content, ResolvedImage):
            self._draw_image(canvas, node.bounds, content, node.opacity, node.source)

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

        for _ in range(saves):
            canvas.restore()  # type: ignore[attr-defined]

    def _mask_path(
        self, mask: MaskSpec, bounds: Rect, source: SourceRef | None
    ) -> object | None:
        generator = self._masks.get(mask.component)
        if generator is None:
            # Compilation rejects unknown masks (ARC-FX-901); guard defensively for isolated use.
            return None
        try:
            params = generator.param_schema(**mask.params)
            return generator.build(params, bounds)
        except Exception as exc:  # noqa: BLE001 - surface a located diagnostic, never a leak
            kwargs: dict[str, Any] = {}
            if source is not None:
                kwargs = {"file": source.file, "keypath": source.keypath, "line": source.line}
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-902",
                    f"Mask {mask.component!r} failed to build: {exc}",
                    hint="Check the mask parameters against its schema.",
                    **kwargs,
                )
            ) from exc

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
            align=text.align,
            language=text.language,
            color=text.color,
            max_width_pt=bounds.w,
            runs=text.runs,
        )
        did_clip = False
        if text.clip:
            canvas.save()  # type: ignore[attr-defined]
            canvas.clipRect(_skrect(bounds))  # type: ignore[attr-defined]
            did_clip = True
        self._text.paint(canvas, req, bounds.x, bounds.y, bounds.w)
        if did_clip:
            canvas.restore()  # type: ignore[attr-defined]

    def _draw_image(
        self,
        canvas: object,
        bounds: Rect,
        image_spec: ResolvedImage,
        opacity: float,
        source: SourceRef | None,
    ) -> None:
        # Missing assets are caught at compile time (ARC-AST-001) so validate reports them.
        # A file that exists but cannot be decoded still reaches here; skia raises
        # ValueError/RuntimeError rather than returning None, so guard the decode and
        # surface a located asset diagnostic (exit 3) instead of an ARC-INT-999 leak.
        try:
            image = skia.Image.open(image_spec.asset_path)
        except (ValueError, RuntimeError) as exc:
            raise _undecodable_image(image_spec.asset_path, source) from exc
        if image is None:
            raise _undecodable_image(image_spec.asset_path, source)
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

    # ------------------------------------------------------------------ debug overlay
    def _draw_debug(self, canvas: object, doc: LayoutDocument) -> None:
        """Overlay node bounds, ids, text baselines, and the safe-area margin.

        Drawn in point space after the scene, deterministically, so a non-debug render is
        never altered. Bounds use their post-rotation AABB (``paint_bounds``) so a rotated
        node is boxed correctly.
        """
        self._draw_safe_area(canvas, doc.canvas.width_pt, doc.canvas.height_pt)
        # DX-9: labels are deconflicted against already-placed ones and clamped into the canvas,
        # deterministically (document order), so dense regions do not overprint into a red smear
        # and corner labels are not clipped off-canvas.
        placed: list[tuple[float, float, float, float]] = []
        self._draw_debug_node(
            canvas, doc.root, doc.canvas.width_pt, doc.canvas.height_pt, placed
        )

    def _draw_debug_node(
        self,
        canvas: object,
        node: LayoutNode,
        canvas_w: float,
        canvas_h: float,
        placed: list[tuple[float, float, float, float]],
    ) -> None:
        if node.visible:
            color = _DEBUG_COLORS.get(node.kind, (1.0, 1.0, 1.0, 1.0))
            box = node.paint_bounds
            paint = _stroke_paint(color, 1.0, 1.0)
            canvas.drawRect(_skrect(box), paint)  # type: ignore[attr-defined]
            lx, ly = _place_label(
                box.x + 1.5, box.y + 1.0, node.source_node_id, canvas_w, canvas_h, placed
            )
            self._draw_debug_label(canvas, lx, ly, node.source_node_id, color)
            if isinstance(node.resolved_content, ResolvedText):
                baseline_y = node.bounds.y + node.resolved_content.font_size_pt
                line = _stroke_paint(color, 0.5, 1.0)
                canvas.drawLine(  # type: ignore[attr-defined]
                    node.bounds.x, baseline_y, node.bounds.right, baseline_y, line
                )
        for child in node.children:
            self._draw_debug_node(canvas, child, canvas_w, canvas_h, placed)

    def _draw_debug_label(
        self, canvas: object, x: float, y_top: float, label: str, color: tuple[float, ...]
    ) -> None:
        req = MeasureRequest(
            text=label,
            font_families=("Inter",),
            font_size_pt=_DEBUG_LABEL_PT,
            font_weight=600,
            color=(color[0], color[1], color[2], color[3]),
            max_width_pt=400.0,
        )
        self._text.paint(canvas, req, x, y_top, 400.0)

    def _draw_safe_area(self, canvas: object, width_pt: float, height_pt: float) -> None:
        mx, my = width_pt * _SAFE_MARGIN_FRAC, height_pt * _SAFE_MARGIN_FRAC
        paint = _stroke_paint(_DEBUG_SAFE_AREA, 0.75, 1.0)
        canvas.drawRect(  # type: ignore[attr-defined]
            skia.Rect.MakeXYWH(mx, my, width_pt - 2 * mx, height_pt - 2 * my), paint
        )


def _place_label(
    x0: float,
    y0: float,
    label: str,
    canvas_w: float,
    canvas_h: float,
    placed: list[tuple[float, float, float, float]],
) -> tuple[float, float]:
    """Return a clamped, deconflicted top-left for a debug label; record its rect (DX-9).

    The label starts at ``(x0, y0)`` (its node's top-left), is clamped so the whole label stays
    on-canvas, then stepped downward past any already-placed label until it finds a free row.
    Placement is a pure function of document order, so it stays deterministic.
    """
    lw = min(400.0, 1.5 + len(label) * _DEBUG_LABEL_PT * 0.62)
    lh = _DEBUG_LABEL_PT + 2.0
    x = max(0.0, min(x0, canvas_w - lw))
    y = max(0.0, min(y0, canvas_h - lh))
    for _ in range(32):
        if not any(_rects_overlap((x, y, lw, lh), p) for p in placed):
            break
        y += lh
        if y + lh > canvas_h:
            # Ran out of room downward: shift right and restart near the original row.
            x = min(x + lw * 0.5, canvas_w - lw)
            y = max(0.0, min(y0, canvas_h - lh))
    placed.append((x, y, lw, lh))
    return x, y


def _rects_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    return (
        a[0] < b[0] + b[2]
        and a[0] + a[2] > b[0]
        and a[1] < b[1] + b[3]
        and a[1] + a[3] > b[1]
    )


def _undecodable_image(asset_path: str, source: SourceRef | None) -> DiagnosticError:
    kwargs: dict[str, Any] = {}
    if source is not None:
        kwargs = {"file": source.file, "keypath": source.keypath, "line": source.line}
    return DiagnosticError(
        diagnostic(
            "ARC-AST-002",
            f"Could not decode image asset: {asset_path}",
            hint="Check that the file is a supported, undamaged image format.",
            **kwargs,
        )
    )


def _visible(node: LayoutNode) -> bool:
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
    color: tuple[float, ...], width_pt: float, opacity: float
) -> object:
    paint = skia.Paint()
    paint.setAntiAlias(True)
    paint.setStyle(skia.Paint.kStroke_Style)
    paint.setStrokeWidth(width_pt)
    paint.setColor4f(skia.Color4f(color[0], color[1], color[2], color[3] * opacity))
    return paint

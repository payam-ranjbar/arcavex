"""Skia renderer backend.

Renders a :class:`LayoutDocument` onto a raster surface sized in device pixels. The canvas is
scaled by ``dpi/72`` so all drawing happens in point coordinates, keeping geometry and text
measurement in the same unit. Traversal is document order with ``z`` already applied by the
layout solver.

A node with no effects takes the direct path: draw its content (and, for a group, its
children) straight onto the canvas, optionally rotated, masked, and faded. A node **with**
effects is rendered offscreen: its content (or subtree) is rasterized into a pooled element
surface covering the node's ``render_bounds`` (layout bounds grown by declared effect
expansion), the category-aware effect plan runs on that raster — geometry rewrites the path
pre-raster, a fused color filter recolors in one pass, raster passes and composite passes
follow (spec §4.4) — and the result is composited back at the right offset, so a drop-shadow or
blur is never clipped. Raster allocations come only from a per-render surface pool (spec §4.5).
Randomness flows exclusively from the seeded effect RNG, so repeated renders are byte-identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.builtin.backend_skia.pipeline import (
    EffectPlan,
    build_color_filter,
    compile_effect_plan,
)
from arcavex.builtin.effects_core.context import (
    CompositeContext,
    GeometryContext,
    RasterContext,
    SurfacePool,
    effect_rng,
)
from arcavex.kernel.contracts.spi import Effect, MaskGenerator, RendererBackend, ShapeGenerator
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
from arcavex.services.assets.probe import probe_image
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
# Debug-overlay label box, drawn only under --debug. The width is an estimate, not a measurement:
# the overlay must not pay for shaping every label, so it multiplies the character count by a
# mean advance-to-size ratio typical of the monospace debug face. Consequences of being wrong are
# cosmetic — a slightly loose or tight background box behind text that is drawn either way.
_DEBUG_LABEL_ADVANCE_RATIO = 0.62
_DEBUG_LABEL_PAD_PT = 1.5
_DEBUG_LABEL_LEADING_PT = 2.0
_DEBUG_LABEL_MAX_W_PT = 400.0
# Deconfliction: step a colliding label down a row, and on reaching the bottom edge start a new
# column half a label to the right. Bounded so a dense scene cannot spin; labels that exhaust the
# attempts simply overlap.
_DEBUG_LABEL_PLACEMENT_TRIES = 32
_DEBUG_LABEL_COLUMN_STEP = 0.5
_EMPTY_PLAN = EffectPlan()


class SkiaBackend(RendererBackend):
    """Renders laid-out documents to Skia raster surfaces."""

    name: ClassVar[str] = "skia"

    def __init__(
        self,
        text_service: TextService,
        masks: dict[str, MaskGenerator] | None = None,
        effects: dict[str, Effect] | None = None,
        shapes: dict[str, ShapeGenerator] | None = None,
        image_cache: object | None = None,
    ) -> None:
        """Bind the backend to the shared text service and the component registries.

        ``image_cache`` is an optional derived-variant cache (spec §4.7): when a large source
        image is drawn into a much smaller slot, the backend fetches a once-downscaled variant
        from it instead of re-decoding the full image every render. It is disposable and never
        authoritative — a *cold cache is byte-identical to a warm one* (the release-gate
        guarantee), because a variant is a pure function of the source bytes and target box.
        Enabling versus disabling the cache is ~1:1, not bit-exact, for ``cover``/``contain``:
        the cache path downscales to the fitted box which ``drawImageRect`` then resamples again
        (two resamples), while ``None`` resamples the full image once. The example scenes stay
        far under the golden DSSIM budget, and production always wires the cache in, so the gate
        rests on cold==warm, not on cache==no-cache.
        """
        self._text = text_service
        self._masks = masks or {}
        self._effects = effects or {}
        self._shapes = shapes or {}
        self._image_cache = image_cache
        # Populated during a render when ``RenderOptions.collect_plan`` is set (debug hook for
        # the fusion test); each entry is ``(node_id, EffectPlan)`` in traversal order.
        self.collected_plans: list[tuple[str, EffectPlan]] = []
        # Per-render scratch, set at the top of ``render`` (no intra-job parallelism, v1).
        self._pool = SurfacePool()
        self._dpi = 72.0
        self._seed = 0
        self._collect = False

    def render(self, doc: LayoutDocument, opts: RenderOptions) -> Surface:
        """Render ``doc`` and return the raster surface."""
        dpi = opts.dpi or doc.canvas.dpi
        width_px = max(1, round(doc.canvas.width_pt * dpi / 72.0))
        height_px = max(1, round(doc.canvas.height_pt * dpi / 72.0))
        self._pool = SurfacePool()
        self._dpi = float(dpi)
        self._seed = doc.seed
        self._collect = opts.collect_plan
        self.collected_plans = []

        surface = skia.Surface(width_px, height_px)
        canvas = surface.getCanvas()
        canvas.clear(skia.Color4f(0, 0, 0, 0))
        canvas.save()
        canvas.scale(dpi / 72.0, dpi / 72.0)
        self._draw_node(canvas, doc.root)
        if opts.debug:
            self._draw_debug(canvas, doc)
        canvas.restore()
        # Leak guard (spec §4.5): every pooled surface acquired by a raster effect is released.
        assert self._pool.outstanding == 0, "surface pool leak: unreleased effect surfaces"
        return surface  # type: ignore[return-value]

    def pool_stats(self) -> dict[str, int]:
        """Return surface-pool counters from the last render (for the reuse/leak test)."""
        return self._pool.stats()

    # ------------------------------------------------------------------ dispatch
    def _draw_node(self, canvas: object, node: LayoutNode) -> None:
        if not _visible(node):
            return
        plan = self._plan_for(node)
        if plan.is_empty:
            self._draw_plain(canvas, node)
        else:
            self._draw_with_effects(canvas, node, plan)

    def _plan_for(self, node: LayoutNode) -> EffectPlan:
        if not node.effects:
            return _EMPTY_PLAN
        plan = compile_effect_plan(node.effects, self._effects)
        if self._collect:
            self.collected_plans.append((node.source_node_id, plan))
        return plan

    # ------------------------------------------------------------------ plain path
    def _draw_plain(self, canvas: object, node: LayoutNode) -> None:
        """Draw a node with no effects directly (rotation, mask, content, then children)."""
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

        self._paint_content(canvas, node, node.opacity)

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

    # ------------------------------------------------------------------ effect path
    def _draw_with_effects(self, canvas: object, node: LayoutNode, plan: EffectPlan) -> None:
        """Rasterize the node offscreen, run its effect plan, then composite it back."""
        rb = node.render_bounds
        scale = self._dpi / 72.0
        w_px = max(1, int(round(rb.w * scale)))
        h_px = max(1, int(round(rb.h * scale)))

        element = self._pool.acquire(w_px, h_px)
        ecanvas = element.getCanvas()
        ecanvas.save()
        ecanvas.scale(scale, scale)
        ecanvas.translate(-rb.x, -rb.y)
        if node.mask is not None:
            mask_path = self._mask_path(node.mask, node.bounds, node.source)
            if mask_path is not None:
                ecanvas.clipPath(mask_path, skia.ClipOp.kIntersect, True)
        self._paint_element_content(ecanvas, node, plan)
        ecanvas.restore()
        image = element.makeImageSnapshot()
        self._pool.release(element)

        # Color stage: one fused, composed color filter applied in a single pass.
        color_filter = build_color_filter(plan.color_ops)
        if color_filter is not None:
            image = self._apply_color(image, color_filter)
        # Raster stage, then composite stage — each an image-in/image-out pass.
        for planned in plan.raster:
            rng = effect_rng(self._seed, node.source_node_id, planned.index)
            ctx = RasterContext(image, planned.params, rng, self._pool, self._dpi)
            image = planned.effect.apply(ctx)
        for planned in plan.composite:
            rng = effect_rng(self._seed, node.source_node_id, planned.index)
            # backdrop is a deferred accessor (always None in v1) — the renderer does not yet
            # snapshot the content painted below in z-order. Tracked in docs/backlog.md; the
            # shipped composite effects (drop-shadow, glow) build only from the element's alpha.
            cctx = CompositeContext(image, None, planned.params, rng, self._pool, self._dpi)
            image = planned.effect.apply(cctx)

        self._composite_back(canvas, node, image, rb)

    def _paint_element_content(
        self, ecanvas: object, node: LayoutNode, plan: EffectPlan
    ) -> None:
        """Paint the node's own content (and children) into the element surface, full opacity."""
        content = node.resolved_content
        if isinstance(content, ResolvedShape) and plan.geometry:
            self._paint_geometry_shape(ecanvas, node, content, plan)
        else:
            self._paint_content(ecanvas, node, 1.0)
        if node.kind == "group" and node.children:
            did_clip = False
            if node.clip:
                ecanvas.save()  # type: ignore[attr-defined]
                ecanvas.clipRect(_skrect(node.bounds))  # type: ignore[attr-defined]
                did_clip = True
            for child in node.children:
                self._draw_node(ecanvas, child)
            if did_clip:
                ecanvas.restore()  # type: ignore[attr-defined]

    def _paint_geometry_shape(
        self, canvas: object, node: LayoutNode, shape: ResolvedShape, plan: EffectPlan
    ) -> None:
        """Apply geometry effects to the shape's path pre-raster, then fill/stroke the result."""
        path = self._shape_path(shape, node.bounds, node.source)
        for planned in plan.geometry:
            rng = effect_rng(self._seed, node.source_node_id, planned.index)
            path = planned.effect.apply(GeometryContext(path, planned.params, rng, node.bounds))
        if shape.fill is not None:
            canvas.drawPath(path, _fill_paint(shape.fill, 1.0))  # type: ignore[attr-defined]
        if shape.stroke is not None and shape.stroke_width_pt > 0:
            canvas.drawPath(  # type: ignore[attr-defined]
                path, _stroke_paint(shape.stroke, shape.stroke_width_pt, 1.0)
            )

    def _apply_color(self, image: object, color_filter: object) -> object:
        paint = skia.Paint()
        paint.setColorFilter(color_filter)
        surface = self._pool.acquire(image.width(), image.height())  # type: ignore[attr-defined]
        surface.getCanvas().drawImage(image, 0, 0, skia.SamplingOptions(), paint)
        out = surface.makeImageSnapshot()
        self._pool.release(surface)
        return out

    def _composite_back(
        self, canvas: object, node: LayoutNode, image: object, rb: Rect
    ) -> None:
        """Draw the finished element image back onto the parent canvas at ``rb`` (points)."""
        canvas.save()  # type: ignore[attr-defined]
        if node.rotate_deg and node.rotate_origin is not None:
            canvas.rotate(node.rotate_deg, node.rotate_origin[0], node.rotate_origin[1])  # type: ignore[attr-defined]
        paint = skia.Paint()
        if node.opacity < 1.0:
            paint.setAlphaf(node.opacity)
        dst = skia.Rect.MakeXYWH(rb.x, rb.y, rb.w, rb.h)
        canvas.drawImageRect(  # type: ignore[attr-defined]
            image, dst, skia.SamplingOptions(), paint
        )
        canvas.restore()  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ content
    def _paint_content(self, canvas: object, node: LayoutNode, opacity: float) -> None:
        content = node.resolved_content
        if isinstance(content, ResolvedShape):
            self._draw_shape(canvas, node.bounds, content, opacity, node.source)
        elif isinstance(content, ResolvedText):
            self._draw_text(canvas, node.bounds, content)
        elif isinstance(content, ResolvedImage):
            self._draw_image(canvas, node.bounds, content, opacity, node.source)

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
            raise _component_error("ARC-FX-902", "Mask", mask.component, exc, source) from exc

    def _shape_path(
        self, shape: ResolvedShape, bounds: Rect, source: SourceRef | None
    ) -> skia.Path:
        """Return the node's shape as a Skia path (generator path or primitive-as-path)."""
        if shape.generator is not None:
            generator = self._shapes.get(shape.generator)
            if generator is None:
                return skia.Path()
            try:
                params = generator.param_schema(**shape.generator_params)
                return generator.build(params, bounds)
            except Exception as exc:  # noqa: BLE001 - located diagnostic, never a leak
                raise _component_error(
                    "ARC-FX-912", "Shape", shape.generator, exc, source
                ) from exc
        path = skia.Path()
        if shape.shape == "circle":
            radius = min(bounds.w, bounds.h) / 2.0
            path.addCircle(bounds.center_x, bounds.center_y, radius)
        elif shape.shape == "rrect" or shape.corner_radius_pt > 0:
            r = shape.corner_radius_pt
            path.addRoundRect(_skrect(bounds), r, r)
        else:
            path.addRect(_skrect(bounds))
        return path

    def _draw_shape(
        self,
        canvas: object,
        bounds: Rect,
        shape: ResolvedShape,
        opacity: float,
        source: SourceRef | None,
    ) -> None:
        if shape.generator is not None:
            path = self._shape_path(shape, bounds, source)
            if shape.fill is not None:
                canvas.drawPath(path, _fill_paint(shape.fill, opacity))  # type: ignore[attr-defined]
            if shape.stroke is not None and shape.stroke_width_pt > 0:
                canvas.drawPath(  # type: ignore[attr-defined]
                    path, _stroke_paint(shape.stroke, shape.stroke_width_pt, opacity)
                )
            return
        rect = _skrect(bounds)
        if shape.fill is not None:
            paint = _fill_paint(shape.fill, opacity)
            self._paint_primitive(canvas, shape, rect, bounds, paint)
        if shape.stroke is not None and shape.stroke_width_pt > 0:
            paint = _stroke_paint(shape.stroke, shape.stroke_width_pt, opacity)
            self._paint_primitive(canvas, shape, rect, bounds, paint)

    def _paint_primitive(
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
        image = self._resolve_image(image_spec, bounds, source)
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

    def _resolve_image(
        self, image_spec: ResolvedImage, bounds: Rect, source: SourceRef | None
    ) -> object:
        """Decode the node's image, using a downscaled cache variant for a large source.

        When a derived cache is wired and the source is much larger than the pixel slot it will
        occupy, a once-downscaled variant (aspect-preserved, so the fit math is unchanged) is used
        instead of the full decode. On a cache miss the cache decodes once; on a hit nothing is
        decoded here. A small image, no cache, or any probe/cache miss falls back to the full
        decode, so the pixels match the no-cache path.
        """
        variant = self._cached_variant(image_spec, bounds)
        if variant is not None:
            return variant
        try:
            image = skia.Image.open(image_spec.asset_path)
        except (ValueError, RuntimeError) as exc:
            raise _undecodable_image(image_spec.asset_path, source) from exc
        if image is None:
            raise _undecodable_image(image_spec.asset_path, source)
        return image

    def _cached_variant(self, image_spec: ResolvedImage, bounds: Rect) -> object | None:
        """Return a downscaled cache variant for a large image, or ``None`` to decode directly."""
        if self._image_cache is None:
            return None
        target = _target_pixels(image_spec, bounds, self._dpi)
        if target is None:
            return None
        try:
            return self._image_cache.variant(Path(image_spec.asset_path), target[0], target[1])  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a disposable cache must never fail a render
            return None

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
    lw = min(
        _DEBUG_LABEL_MAX_W_PT,
        _DEBUG_LABEL_PAD_PT + len(label) * _DEBUG_LABEL_PT * _DEBUG_LABEL_ADVANCE_RATIO,
    )
    lh = _DEBUG_LABEL_PT + _DEBUG_LABEL_LEADING_PT
    x = max(0.0, min(x0, canvas_w - lw))
    y = max(0.0, min(y0, canvas_h - lh))
    for _ in range(_DEBUG_LABEL_PLACEMENT_TRIES):
        if not any(_rects_overlap((x, y, lw, lh), p) for p in placed):
            break
        y += lh
        if y + lh > canvas_h:
            # Ran out of room downward: shift right and restart near the original row.
            x = min(x + lw * _DEBUG_LABEL_COLUMN_STEP, canvas_w - lw)
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


def _component_error(
    code: str, kind: str, name: str, exc: Exception, source: SourceRef | None
) -> DiagnosticError:
    kwargs: dict[str, Any] = {}
    if source is not None:
        kwargs = {"file": source.file, "keypath": source.keypath, "line": source.line}
    return DiagnosticError(
        diagnostic(
            code,
            f"{kind} {name!r} failed to build: {exc}",
            hint=f"Check the {kind.lower()} parameters against its schema.",
            **kwargs,
        )
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


def _target_pixels(
    image_spec: ResolvedImage, bounds: Rect, dpi: float
) -> tuple[int, int] | None:
    """Return the device-pixel box the image will occupy, preserving its aspect (or ``None``).

    The box mirrors the fit math in :meth:`_draw_image` so a variant downscaled to it draws
    ~1:1: for ``fill`` it is the node's device-pixel bounds; for ``contain``/``cover`` it is the
    source scaled uniformly to fit/cover the bounds, so the source aspect is kept. Source
    dimensions come from the file header (a few bytes), never a full decode; a header that will
    not probe returns ``None`` so the caller decodes directly.
    """
    scale = dpi / 72.0
    if image_spec.fit == "fill":
        return max(1, round(bounds.w * scale)), max(1, round(bounds.h * scale))
    try:
        with open(image_spec.asset_path, "rb") as handle:
            header = handle.read(131072)
        probe = probe_image(header, source=image_spec.asset_path)
    except Exception:  # noqa: BLE001 - probe failure just means "decode directly"
        return None
    iw, ih = float(probe.width), float(probe.height)
    if iw <= 0 or ih <= 0:
        return None
    if image_spec.fit == "cover":
        fit = max(bounds.w / iw, bounds.h / ih)
    else:  # contain
        fit = min(bounds.w / iw, bounds.h / ih)
    return max(1, round(iw * fit * scale)), max(1, round(ih * fit * scale))


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

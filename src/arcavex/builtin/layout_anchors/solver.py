"""Anchor + stack layout solver (spec §4.2).

An understandable anchor *resolver*, not a general constraint solver. Each node resolves
exactly one horizontal position, one vertical position, a width, and a height. Positions come
from parent or named-sibling anchors (with logical ``start``/``end`` resolved through the
enclosing group's direction), or from a stack (``hstack``/``vstack``) that flows its children.
Sizes come from ``fixed``/``percent``/``fill``/``fit_content``/``aspect`` modes with optional
``min``/``max`` clamps. Text fit policies run through the injected text-measurement function
(the single shaper). Rotations contribute a post-transform AABB to paint bounds. The input
:class:`CompiledDocument` is never mutated; a fresh :class:`LayoutDocument` is returned with
final geometry normalized to 1/1024 pt. Non-fatal issues (missing glyphs, fit non-convergence)
are collected as ``warnings`` on the document; contradictions raise located ``ARC-LAY`` errors.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Sequence
from typing import Any, ClassVar, NoReturn

from arcavex.kernel.contracts.spi import Effect, LayoutSolver
from arcavex.kernel.contracts.types import MeasureFn, MeasureRequest, MeasureResult
from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic
from arcavex.kernel.ir.models import (
    AnchorEdge,
    CompiledDocument,
    CompiledGroup,
    CompiledImage,
    CompiledNode,
    CompiledShape,
    CompiledText,
    EffectSpec,
    LayoutDocument,
    LayoutNode,
    OverflowState,
    ResolvedContent,
    ResolvedImage,
    ResolvedRun,
    ResolvedShape,
    ResolvedText,
    SizeSpec,
    StackSpec,
    TextRun,
)
from arcavex.kernel.ir.units import Insets, Matrix3, Rect

_QUANT = 1024.0
_HORIZONTAL = ("left", "right", "center_x")
_VERTICAL = ("top", "bottom", "center_y")
# Safety margin added to a fit_content *width*. It is NOT about 1/1024pt geometry quantization
# (that step is ~0.001pt — three orders of magnitude smaller than this cushion). The real cause
# is SkParagraph re-layout sensitivity: the longest-line width reported by a measurement pass,
# fed straight back as the layout max-width, can leave the same line a hair too wide to fit and
# re-wrap it. Half a point reliably absorbs that boundary jitter without visibly widening boxes.
_FIT_WIDTH_MARGIN = 0.5


def _q(value: float) -> float:
    return round(value * _QUANT) / _QUANT


def _qrect(x: float, y: float, w: float, h: float) -> Rect:
    return Rect(_q(x), _q(y), _q(max(0.0, w)), _q(max(0.0, h)))


class AnchorLayoutSolver(LayoutSolver):
    """Absolute-anchor and stack layout solver."""

    name: ClassVar[str] = "anchors"

    def __init__(self, effects: dict[str, Effect] | None = None) -> None:
        """Bind the solver to the effect registry so ``paint_bounds`` reflects effect growth.

        Layout bounds always exclude visual effect expansion (spec §4.2); the effects are used
        only to grow ``paint_bounds``/``render_bounds`` so the renderer allocates room for a
        drop-shadow or blur. When no registry is supplied (isolated unit tests), effect
        expansion is treated as zero.
        """
        self._effects = effects or {}

    def solve(self, doc: CompiledDocument, measure: MeasureFn) -> LayoutDocument:
        """Resolve geometry for every node into a new layout document."""
        warnings: list[Diagnostic] = []
        canvas = Rect(0.0, 0.0, doc.canvas.width_pt, doc.canvas.height_pt)
        root = self._solve_node(doc.root, canvas, doc.root.direction, measure, warnings)
        return LayoutDocument(
            canvas=_resolved_canvas(doc),
            seed=doc.seed,
            root=root,
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------ node solve
    def _solve_node(
        self,
        node: CompiledNode,
        bounds: Rect,
        inherited_dir: str,
        measure: MeasureFn,
        warnings: list[Diagnostic],
    ) -> LayoutNode:
        rotate_deg = node.transform.rotate_deg
        origin = self._origin_abs(node, bounds) if rotate_deg else None

        content, overflow = self._resolve_content(node, bounds, inherited_dir, measure, warnings)

        children: tuple[LayoutNode, ...] = ()
        clip = False
        if isinstance(node, CompiledGroup):
            clip = node.clip
            child_dir = node.direction
            child_rects = self._layout_children(node, bounds, measure, warnings)
            children = tuple(
                self._solve_node(child, rect, child_dir, measure, warnings)
                for child, rect in child_rects
            )

        # Effect expansion grows the node-local render rectangle (pre-rotation); paint_bounds is
        # that expanded rectangle's post-rotation AABB. Layout/anchoring still use `bounds`.
        expansion = self._effect_expansion(node.effects)
        render_bounds = bounds.expanded(expansion)
        paint_bounds = self._paint_bounds(render_bounds, rotate_deg, origin)
        return LayoutNode(
            source_node_id=node.id,
            kind=node.type,
            bounds=bounds,
            absolute_transform=self._transform(rotate_deg, origin),
            paint_bounds=paint_bounds,
            render_bounds=render_bounds,
            effects=node.effects,
            overflow=overflow,
            rotate_deg=rotate_deg,
            rotate_origin=origin,
            opacity=node.style.opacity,
            visible=node.visible,
            clip=clip,
            mask=node.mask,
            resolved_content=content,
            children=children,
            source=node.source,
        )

    # ------------------------------------------------------------------ children
    def _layout_children(
        self, group: CompiledGroup, bounds: Rect, measure: MeasureFn, warnings: list[Diagnostic]
    ) -> list[tuple[CompiledNode, Rect]]:
        if group.stack.kind == "absolute":
            rects = self._absolute_children(group, bounds, measure, warnings)
        else:
            rects = self._stack_children(group, bounds, measure, warnings)
        # Draw order is document order broken by z (stable, matches Phase 0).
        indexed = {c.id: i for i, c in enumerate(group.children)}
        return sorted(rects, key=lambda pair: (pair[0].z, indexed[pair[0].id]))

    def _absolute_children(
        self, group: CompiledGroup, bounds: Rect, measure: MeasureFn, warnings: list[Diagnostic]
    ) -> list[tuple[CompiledNode, Rect]]:
        by_id = {c.id: c for c in group.children}
        order = self._topo_order(group, by_id)
        sib_rects: dict[str, Rect] = {}
        out: list[tuple[CompiledNode, Rect]] = []
        for child in order:
            rect = self._resolve_absolute(child, bounds, group.direction, sib_rects, measure)
            # Siblings anchor to the *post-rotation* AABB of a rotated node (spec §4.2), so a
            # node pinned to a 45°-rotated square's `bottom` sees the rotated extent (CR-14).
            sib_rects[child.id] = self._aabb_for(child, rect)
            out.append((child, rect))
        return out

    def _aabb_for(self, node: CompiledNode, rect: Rect) -> Rect:
        """Return the axis-aligned bounding box a sibling sees: the paint AABB when rotated."""
        deg = node.transform.rotate_deg
        if not deg:
            return rect
        return self._paint_bounds(rect, deg, self._origin_abs(node, rect))

    def _topo_order(
        self, group: CompiledGroup, by_id: dict[str, CompiledNode]
    ) -> list[CompiledNode]:
        """Order children so every sibling anchor target resolves first; cycle -> ARC-LAY-052."""
        deps: dict[str, list[str]] = {}
        for child in group.children:
            refs: list[str] = []
            for anchor in child.constraints.anchors.values():
                if anchor.ref != "parent":
                    if anchor.ref not in by_id:
                        raise DiagnosticError(
                            diagnostic(
                                "ARC-LAY-053",
                                f"Node {child.id!r} anchors to unknown sibling {anchor.ref!r}",
                                hint="Anchor to a sibling id in the same group, or to 'parent'.",
                                **_loc(child),
                            )
                        )
                    refs.append(anchor.ref)
            deps[child.id] = refs

        state: dict[str, int] = {}  # 0=unvisited,1=visiting,2=done
        order: list[str] = []
        stack_path: list[str] = []

        def visit(node_id: str) -> None:
            mark = state.get(node_id, 0)
            if mark == 2:
                return
            if mark == 1:
                cycle = stack_path[stack_path.index(node_id):] + [node_id]
                child = by_id[node_id]
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LAY-052",
                        f"Sibling anchor cycle: {' -> '.join(cycle)}",
                        hint="Break the loop so one node anchors to a node resolved before it.",
                        **_loc(child),
                    )
                )
            state[node_id] = 1
            stack_path.append(node_id)
            for ref in deps[node_id]:
                visit(ref)
            stack_path.pop()
            state[node_id] = 2
            order.append(node_id)

        for child in group.children:
            visit(child.id)
        return [by_id[i] for i in order]

    def _stack_children(
        self, group: CompiledGroup, bounds: Rect, measure: MeasureFn, warnings: list[Diagnostic]
    ) -> list[tuple[CompiledNode, Rect]]:
        stack = group.stack
        content = Rect(
            bounds.x + stack.pad_left_pt,
            bounds.y + stack.pad_top_pt,
            max(0.0, bounds.w - stack.pad_left_pt - stack.pad_right_pt),
            max(0.0, bounds.h - stack.pad_top_pt - stack.pad_bottom_pt),
        )
        horizontal = stack.kind == "hstack"
        main_extent = content.w if horizontal else content.h
        cross_extent = content.h if horizontal else content.w

        for child in group.children:
            if child.constraints.anchors:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LAY-054",
                        f"Stack child {child.id!r} declares position anchors",
                        hint="A stack positions its children; remove the 'anchor' block.",
                        **_loc(child),
                    )
                )

        # Each entry carries (main, cross, main_is_fill, main_spec, cross_spec) so the placement
        # pass can clamp fill/stretch shares against the child's own min/max (CR-12).
        sizes: list[tuple[float, float, bool, SizeSpec, SizeSpec]] = []
        for child in group.children:
            main_spec = child.constraints.width if horizontal else child.constraints.height
            cross_spec = child.constraints.height if horizontal else child.constraints.width
            main_is_fill = main_spec.mode == "fill"
            cross, main = self._stack_child_sizes(
                child, main_spec, cross_spec, main_extent, cross_extent, stack,
                horizontal, main_is_fill, measure,
            )
            sizes.append((main, cross, main_is_fill, main_spec, cross_spec))

        n = len(group.children)
        gaps_total = stack.gap_pt * max(0, n - 1)
        fixed_main = sum(m for m, _, is_fill, _, _ in sizes if not is_fill)
        fill_count = sum(1 for _, _, is_fill, _, _ in sizes if is_fill)
        free = max(0.0, main_extent - fixed_main - gaps_total)
        # Resolve fill shares with min/max clamps, redistributing freed space to the other fill
        # children (RR2-8): a fill child capped by its own max/min no longer starves or hogs its
        # siblings. Iterate to a fixed point, removing each newly clamped child from the pool.
        fill_sizes = self._resolve_fill_sizes(sizes, free)
        fill_used = sum(fill_sizes.values())
        # Any space the fill children could not absorb (all clamped) becomes alignable leftover.
        leftover = free if fill_count == 0 else max(0.0, free - fill_used)

        cursor, gap = self._stack_start(stack.main_align, leftover, stack.gap_pt, n)
        out: list[tuple[CompiledNode, Rect]] = []
        for idx, (child, (main, cross, is_fill, _main_spec, cross_spec)) in enumerate(
            zip(group.children, sizes, strict=True)
        ):
            m = fill_sizes[idx] if is_fill else main
            cross_pos, cross_len = self._cross_place(stack.cross_align, cross, cross_extent)
            cross_len = _clamp(cross_len, cross_spec)
            if horizontal:
                rect = _qrect(content.x + cursor, content.y + cross_pos, m, cross_len)
            else:
                rect = _qrect(content.x + cross_pos, content.y + cursor, cross_len, m)
            out.append((child, rect))
            cursor += m + gap
        if group.direction == "rtl":
            # RTL mirrors the horizontal axis within the content box: for an hstack this flips
            # packing order and main_align (first child sits at the right edge); for a vstack it
            # flips cross-axis start/end. The vertical (reading) axis is never mirrored (DX-1).
            out = [(child, _mirror_x(rect, content)) for child, rect in out]
        return out

    def _resolve_fill_sizes(
        self,
        sizes: list[tuple[float, float, bool, SizeSpec, SizeSpec]],
        free: float,
    ) -> dict[int, float]:
        """Return the resolved main size for each fill child, redistributing clamp overflow.

        Fill children split the free main-axis space equally; a child whose ``min``/``max``
        clamps its share is fixed at the clamped value and dropped from the pool, and the
        remaining space is re-split among the rest. Repeats to a fixed point (RR2-8), so a
        capped sibling gives its surplus (or takes its deficit) from the others rather than
        leaving them starved.
        """
        unresolved = {i for i, s in enumerate(sizes) if s[2]}
        resolved: dict[int, float] = {}
        remaining = free
        while unresolved:
            share = remaining / len(unresolved)
            newly_clamped: list[int] = []
            for i in unresolved:
                clamped = _clamp(share, sizes[i][3])
                if abs(clamped - share) > 1e-9:
                    resolved[i] = clamped
                    newly_clamped.append(i)
            if not newly_clamped:
                for i in unresolved:
                    resolved[i] = share
                break
            for i in newly_clamped:
                unresolved.discard(i)
                remaining -= resolved[i]
            remaining = max(0.0, remaining)
        return resolved

    def _stack_child_sizes(
        self,
        child: CompiledNode,
        main_spec: SizeSpec,
        cross_spec: SizeSpec,
        main_extent: float,
        cross_extent: float,
        stack: StackSpec,
        horizontal: bool,
        main_is_fill: bool,
        measure: MeasureFn,
    ) -> tuple[float, float]:
        """Return ``(cross, main)`` sizes for one stack child.

        A cross-axis ``aspect`` derives from the concrete main size (CR-5); it is unresolvable
        when the main axis is itself ``aspect`` or ``fill`` (no fixed extent to derive from).
        """
        if cross_spec.mode == "aspect":
            if main_spec.mode == "aspect" or main_is_fill:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LAY-055",
                        f"Stack child {child.id!r} uses cross-axis 'aspect' but its main axis "
                        f"has no concrete size to derive from",
                        hint="Give the main axis a fixed/%/fit_content size so 'aspect' can "
                        "derive the cross axis.",
                        **_loc(child),
                    )
                )
            main = self._stack_main_size(
                child, main_spec, cross_spec, main_extent, 0.0, horizontal, measure
            )
            cross = _clamp(_aspect_value(cross_spec, main, child), cross_spec)
            return cross, main
        cross = self._cross_size(child, cross_spec, cross_extent, stack, measure)
        if main_is_fill:
            return cross, 0.0
        main = self._stack_main_size(
            child, main_spec, cross_spec, main_extent, cross, horizontal, measure
        )
        return cross, main

    @staticmethod
    def _stack_start(
        align: str, leftover: float, gap: float, n: int
    ) -> tuple[float, float]:
        """Return the starting main-axis offset and the effective inter-item gap."""
        if align == "center":
            return leftover / 2.0, gap
        if align == "end":
            return leftover, gap
        if align == "space_between" and n > 1:
            return 0.0, gap + leftover / (n - 1)
        return 0.0, gap

    @staticmethod
    def _cross_place(align: str, size: float, extent: float) -> tuple[float, float]:
        if align == "stretch":
            return 0.0, extent
        if align == "center":
            return max(0.0, (extent - size) / 2.0), size
        if align == "end":
            return max(0.0, extent - size), size
        return 0.0, size

    def _cross_size(
        self,
        child: CompiledNode,
        spec: SizeSpec,
        cross_extent: float,
        stack: StackSpec,
        measure: MeasureFn,
    ) -> float:
        if stack.cross_align == "stretch" or spec.mode == "fill":
            return cross_extent
        if spec.mode == "aspect":
            # Cross derived from main needs main first; resolved in the main pass instead.
            return 0.0
        return _clamp(self._axis_size(child, spec, cross_extent, None, measure), spec)

    def _stack_main_size(
        self,
        child: CompiledNode,
        main_spec: SizeSpec,
        cross_spec: SizeSpec,
        main_extent: float,
        cross: float,
        horizontal: bool,
        measure: MeasureFn,
    ) -> float:
        if main_spec.mode == "aspect":
            other = cross
            return _clamp(_aspect_value(main_spec, other, child), main_spec)
        width = cross if not horizontal else None
        return _clamp(self._axis_size(child, main_spec, main_extent, width, measure), main_spec)

    # ------------------------------------------------------------------ absolute node
    def _resolve_absolute(
        self,
        node: CompiledNode,
        parent: Rect,
        group_dir: str,
        sib_rects: dict[str, Rect],
        measure: MeasureFn,
    ) -> Rect:
        w, h = self._resolve_size(node, parent, measure)
        x = self._resolve_pos(node, parent, group_dir, sib_rects, w, _HORIZONTAL, "horizontal")
        y = self._resolve_pos(node, parent, group_dir, sib_rects, h, _VERTICAL, "vertical")
        return _qrect(x, y, w, h)

    def _resolve_size(
        self, node: CompiledNode, parent: Rect, measure: MeasureFn
    ) -> tuple[float, float]:
        wspec, hspec = node.constraints.width, node.constraints.height
        if wspec.mode == "aspect" and hspec.mode == "aspect":
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-055",
                    f"Node {node.id!r} declares 'aspect' on both axes",
                    hint="Give one axis a concrete size; 'aspect' derives the other.",
                    **_loc(node),
                )
            )
        # Resolve and clamp the non-aspect axis first, so the aspect axis derives from the
        # *clamped* other extent (CR-4) and then applies its own min/max clamp.
        w = (
            None
            if wspec.mode == "aspect"
            else _clamp(self._axis_size(node, wspec, parent.w, None, measure), wspec)
        )
        h = (
            None
            if hspec.mode == "aspect"
            else _clamp(self._axis_size(node, hspec, parent.h, w, measure), hspec)
        )
        if wspec.mode == "aspect":
            w = _clamp(_aspect_value(wspec, h, node), wspec)
        if hspec.mode == "aspect":
            h = _clamp(_aspect_value(hspec, w, node), hspec)
        assert w is not None and h is not None
        return w, h

    def _axis_size(
        self,
        node: CompiledNode,
        spec: SizeSpec,
        basis: float,
        width: float | None,
        measure: MeasureFn,
    ) -> float:
        if spec.mode == "fixed":
            return float(spec.value_pt or 0.0)
        if spec.mode == "percent":
            return basis * float(spec.percent or 0.0) / 100.0
        if spec.mode == "fill":
            return basis
        if spec.mode == "aspect":  # resolved by caller
            return 0.0
        # fit_content — text intrinsic (width when width is None, else height at that width).
        result = self._measure_text(node, width, None, measure)
        if width is None:
            # Cushion the measured longest-line width so feeding it back as the paint-time
            # max-width does not re-wrap the same line (SkParagraph re-layout sensitivity, not
            # geometry quantization — see _FIT_WIDTH_MARGIN).
            return result.width_pt + _FIT_WIDTH_MARGIN
        height = result.height_pt
        # DX-7: a fit_content box that also sets max_lines caps its height at that many lines,
        # otherwise the box grows to the full text and max_lines has nothing to clip.
        max_lines = node.fit.max_lines if isinstance(node, CompiledText) else None
        if max_lines is not None and result.line_count > max_lines and result.line_count > 0:
            height = height * max_lines / result.line_count
        return height

    def _resolve_pos(
        self,
        node: CompiledNode,
        parent: Rect,
        group_dir: str,
        sib_rects: dict[str, Rect],
        size: float,
        axis_keys: tuple[str, ...],
        axis_name: str,
    ) -> float:
        anchors = node.constraints.anchors
        present: list[tuple[str, AnchorEdge]] = []
        for key, anchor in anchors.items():
            phys = _logical(key, group_dir)
            if phys in axis_keys:
                present.append((phys, anchor))
        self._require_single(node, [p for p, _ in present], axis_name)
        phys_key, anchor = present[0]
        ref_rect = parent if anchor.ref == "parent" else sib_rects[anchor.ref]
        ref_edge = _logical(anchor.edge, group_dir)
        # A logical (start/end) reference edge takes its offset in reading order: '+d' moves
        # toward the end, which is +x in ltr but -x in rtl. Physical edges keep the raw offset.
        offset = anchor.offset_pt
        if anchor.edge in ("start", "end") and group_dir == "rtl":
            offset = -offset
        ref_pos = _edge_pos(ref_edge, ref_rect) + offset
        if phys_key in ("left", "top"):
            return ref_pos
        if phys_key in ("right", "bottom"):
            return ref_pos - size
        return ref_pos - size / 2.0

    def _require_single(self, node: CompiledNode, present: Sequence[str], axis: str) -> None:
        options = "left/right/start/end/center_x" if axis == "horizontal" else "top/bottom/center_y"
        if len(present) == 0:
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-030",
                    f"Node {node.id!r} is under-constrained on the {axis} axis",
                    hint=f"Add exactly one {axis} anchor ({options}).",
                    **_loc(node),
                )
            )
        if len(present) > 1:
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-031",
                    f"Node {node.id!r} is over-constrained on the {axis} axis: "
                    f"{', '.join(present)}",
                    hint=f"Keep exactly one {axis} anchor; size comes from the size spec.",
                    **_loc(node),
                )
            )

    # ------------------------------------------------------------------ content
    def _resolve_content(
        self,
        node: CompiledNode,
        bounds: Rect,
        inherited_dir: str,
        measure: MeasureFn,
        warnings: list[Diagnostic],
    ) -> tuple[ResolvedContent, OverflowState]:
        if isinstance(node, CompiledText):
            return self._resolve_text(node, bounds, inherited_dir, measure, warnings)
        if isinstance(node, CompiledImage):
            return ResolvedImage(asset_path=node.asset_path, fit=node.fit), OverflowState()
        if isinstance(node, CompiledShape):
            return (
                ResolvedShape(
                    shape=node.shape,
                    fill=node.style.fill,
                    stroke=node.style.stroke,
                    stroke_width_pt=node.style.stroke_width_pt,
                    corner_radius_pt=node.style.corner_radius_pt,
                    generator=node.generator,
                    generator_params=node.generator_params,
                ),
                OverflowState(),
            )
        return None, OverflowState()

    def _resolve_text(
        self,
        node: CompiledText,
        bounds: Rect,
        inherited_dir: str,
        measure: MeasureFn,
        warnings: list[Diagnostic],
    ) -> tuple[ResolvedText, OverflowState]:
        direction = _resolve_dir(node.paragraph.direction, node.text, inherited_dir)
        base_size = node.style.font_size_pt or 16.0
        runs = _base_runs(node, base_size)
        bounded_height = node.constraints.height.mode != "fit_content"
        req = self._text_request(
            node, runs, base_size, direction,
            max_width=bounds.w,
            max_height=bounds.h if bounded_height else None,
        )
        result = measure(req)
        for cp, families in result.missing_glyphs:
            warnings.append(_missing_glyph_diag(node, cp, families))

        scale = (result.resolved_size_pt or base_size) / base_size if base_size else 1.0
        out_runs = _scale_runs(runs, scale, result.out_text)
        kind = result.overflow_kind
        clip = kind == "truncated"
        if kind == "overflowing":
            if node.fit.overflow == "error":
                self._raise_overflow(node, bounds, result)
            if node.fit.overflow == "clip":
                kind, clip = "clipped", True
        if not result.converged:
            if node.fit.policy == "truncate":
                warnings.append(
                    diagnostic(
                        "ARC-LAY-051",
                        f"Text node {node.id!r} box is shorter than its text needs "
                        f"({bounds.h:.1f}pt tall, the fitted text is {result.height_pt:.1f}pt); "
                        f"truncation left only the ellipsis",
                        severity="warning",
                        hint="Give the box at least one line's height, or reduce the font size.",
                        **_loc(node),
                    )
                )
            else:
                warnings.append(
                    diagnostic(
                        "ARC-LAY-051",
                        f"Text node {node.id!r} did not converge under 'shrink_to_fit' "
                        f"(still {result.height_pt:.1f}pt tall at min size in a "
                        f"{bounds.h:.1f}pt box)",
                        severity="warning",
                        hint=(
                            "Lower min_size (it is the shrink floor, so raising it makes this "
                            "worse), enlarge the box, or switch to truncate."
                        ),
                        **_loc(node),
                    )
                )
        resolved = ResolvedText(
            text=result.out_text or node.text,
            runs=out_runs,
            font_families=out_runs[0].font_families if out_runs else ("Inter",),
            font_size_pt=result.resolved_size_pt or base_size,
            font_weight=node.style.font_weight,
            italic=node.style.italic,
            color=node.style.text_color or (0.0, 0.0, 0.0, 1.0),
            align=node.paragraph.align,
            direction=direction,
            line_height=node.style.line_height,
            letter_spacing_pt=node.style.letter_spacing_pt,
            language=node.style.language,
            clip=clip,
        )
        overflow = OverflowState(
            kind=kind,  # type: ignore[arg-type]
            measured_w_pt=_q(result.width_pt),
            measured_h_pt=_q(result.height_pt),
            box_w_pt=bounds.w,
            box_h_pt=bounds.h,
            resolved_size_pt=result.resolved_size_pt or base_size,
        )
        return resolved, overflow

    def _raise_overflow(
        self, node: CompiledText, bounds: Rect, result: MeasureResult
    ) -> NoReturn:
        """Raise the overflow error that names the constraint actually blocking the fit.

        Two genuinely different failures reach here. When 'shrink_to_fit' bottomed out at its
        min_size floor and the text *still* wraps onto more lines than 'max_lines' allows —
        while every line does fit the box width — the binding constraint is the line cap, not
        the box. The measured height in that state is simply what those lines occupy, so
        quoting a measured-vs-box height pair points at the one dimension that cannot fix it:
        enlarging the box height leaves the cap violated and re-reports the same number
        (ARC-LAY-057). Every other case is a real box-geometry overflow and keeps ARC-LAY-050,
        whose measured-vs-box extents are the useful thing to show.
        """
        max_lines = node.fit.max_lines
        # The width comparison reuses _FIT_WIDTH_MARGIN for the reason it exists: absorbing
        # SkParagraph's longest-line-vs-max-width boundary jitter, the same comparison made here.
        if (
            node.fit.policy == "shrink_to_fit"
            and not result.converged
            and max_lines is not None
            and result.line_count > max_lines
            and result.width_pt <= bounds.w + _FIT_WIDTH_MARGIN
        ):
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-057",
                    f"Text node {node.id!r} still needs {result.line_count} lines at its "
                    f"{result.resolved_size_pt:.1f}pt shrink floor but 'max_lines' is "
                    f"{max_lines}, and overflow is 'error'",
                    hint="Widen the box, lower 'fit.min_size', or raise 'max_lines'. "
                    "Enlarging the box height will not help.",
                    **_loc(node),
                )
            )
        raise DiagnosticError(
            diagnostic(
                "ARC-LAY-050",
                f"Text node {node.id!r} overflows its box "
                f"({result.width_pt:.1f}x{result.height_pt:.1f}pt into "
                f"{bounds.w:.1f}x{bounds.h:.1f}pt) and overflow is 'error'",
                hint="Enlarge the box, shrink the text, or set overflow to clip/allow.",
                **_loc(node),
            )
        )

    def _measure_text(
        self,
        node: CompiledNode,
        width: float | None,
        height: float | None,
        measure: MeasureFn,
    ) -> MeasureResult:
        if not isinstance(node, CompiledText):
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-020",
                    f"Node {node.id!r} uses 'fit_content' but is not a text node",
                    hint="Only text nodes support fit_content; give images/groups a fixed size.",
                    **_loc(node),
                )
            )
        base_size = node.style.font_size_pt or 16.0
        runs = _base_runs(node, base_size)
        direction = _resolve_dir(node.paragraph.direction, node.text, "ltr")
        req = self._text_request(node, runs, base_size, direction, width, height)
        return measure(req)

    def _text_request(
        self,
        node: CompiledText,
        runs: tuple[ResolvedRun, ...],
        base_size: float,
        direction: str,
        max_width: float | None,
        max_height: float | None,
    ) -> MeasureRequest:
        return MeasureRequest(
            text=node.text,
            font_families=runs[0].font_families if runs else ("Inter",),
            font_size_pt=base_size,
            font_weight=node.style.font_weight,
            italic=node.style.italic,
            letter_spacing_pt=node.style.letter_spacing_pt,
            line_height=node.style.line_height,
            direction=direction,  # type: ignore[arg-type]
            align=node.paragraph.align,
            language=node.style.language,
            color=node.style.text_color or (0.0, 0.0, 0.0, 1.0),
            max_width_pt=max_width,
            max_height_pt=max_height,
            runs=runs,
            fit_policy=node.fit.policy,
            min_size_pt=node.fit.min_size_pt,
            max_lines=node.fit.max_lines,
        )

    # ------------------------------------------------------------------ transforms
    def _origin_abs(self, node: CompiledNode, bounds: Rect) -> tuple[float, float]:
        origin = node.transform.origin
        if origin is None:
            return bounds.center_x, bounds.center_y
        return bounds.x + bounds.w * origin[0], bounds.y + bounds.h * origin[1]

    def _transform(self, deg: float, origin: tuple[float, float] | None) -> Matrix3:
        if not deg or origin is None:
            return Matrix3.identity()
        rad = math.radians(deg)
        cos, sin = math.cos(rad), math.sin(rad)
        ox, oy = origin
        return Matrix3(
            a=cos, b=sin, c=-sin, d=cos,
            e=ox - ox * cos + oy * sin,
            f=oy - ox * sin - oy * cos,
        )

    def _effect_expansion(self, effects: tuple[EffectSpec, ...]) -> Insets:
        """Sum every effect's declared outward growth per side (spec §4.4).

        Effects apply in sequence and each grows relative to its input, so the safe paint
        region is the per-side sum of their declared expansions. With one effect this is exact,
        which is what the per-effect bounds-honesty test relies on.
        """
        top = right = bottom = left = 0.0
        for spec in effects:
            effect = self._effects.get(spec.name)
            if effect is None:
                continue
            insets = effect.bounds_expansion(effect.param_schema(**spec.params))
            top += insets.top
            right += insets.right
            bottom += insets.bottom
            left += insets.left
        return Insets(top=top, right=right, bottom=bottom, left=left)

    def _paint_bounds(
        self, bounds: Rect, deg: float, origin: tuple[float, float] | None
    ) -> Rect:
        if not deg or origin is None:
            return bounds
        matrix = self._transform(deg, origin)
        corners = [
            matrix.apply(bounds.x, bounds.y),
            matrix.apply(bounds.right, bounds.y),
            matrix.apply(bounds.right, bounds.bottom),
            matrix.apply(bounds.x, bounds.bottom),
        ]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return _qrect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


# --------------------------------------------------------------------------- helpers
def _resolved_canvas(doc: CompiledDocument):  # noqa: ANN202
    from arcavex.kernel.ir.models import ResolvedCanvas

    return ResolvedCanvas(
        width_pt=doc.canvas.width_pt, height_pt=doc.canvas.height_pt, dpi=doc.canvas.dpi
    )


def _loc(node: CompiledNode) -> dict[str, Any]:
    """Return located-diagnostic kwargs (file/keypath/line) from a node's carried source."""
    src = node.source
    if src is None:
        return {}
    return {"file": src.file, "keypath": src.keypath, "line": src.line}


def _mirror_x(rect: Rect, content: Rect) -> Rect:
    """Reflect a rect horizontally within ``content`` (RTL stack mirroring, DX-1)."""
    new_x = content.x + content.w - (rect.x - content.x) - rect.w
    return _qrect(new_x, rect.y, rect.w, rect.h)


def _logical(edge: str, direction: str) -> str:
    if edge == "start":
        return "left" if direction == "ltr" else "right"
    if edge == "end":
        return "right" if direction == "ltr" else "left"
    return edge


def _edge_pos(edge: str, rect: Rect) -> float:
    return {
        "top": rect.y,
        "bottom": rect.bottom,
        "center_y": rect.center_y,
        "left": rect.x,
        "right": rect.right,
        "center_x": rect.center_x,
    }[edge]


def _clamp(value: float, spec: SizeSpec) -> float:
    if spec.min_pt is not None:
        value = max(value, spec.min_pt)
    if spec.max_pt is not None:
        value = min(value, spec.max_pt)
    return value


def _aspect_value(spec: SizeSpec, other: float | None, node: CompiledNode) -> float:
    if other is None:
        raise DiagnosticError(
            diagnostic(
                "ARC-LAY-055",
                f"Node {node.id!r} uses 'aspect' but the other axis is not resolvable",
                hint="Give the other axis a concrete size (fixed/%/fill) for aspect to derive.",
                **_loc(node),
            )
        )
    ratio = (spec.aspect_w or 1.0) / (spec.aspect_h or 1.0)
    return other * ratio


def _base_runs(node: CompiledText, base_size: float) -> tuple[ResolvedRun, ...]:
    style = node.style
    families = style.font_families or ("Inter",)
    color = style.text_color or (0.0, 0.0, 0.0, 1.0)
    source: Sequence[TextRun]
    if node.runs:
        source = node.runs
    else:
        source = (TextRun(text=node.text),)
    out: list[ResolvedRun] = []
    for run in source:
        out.append(
            ResolvedRun(
                text=run.text,
                font_families=run.font_families or families,
                font_size_pt=run.font_size_pt or base_size,
                font_weight=run.font_weight if run.font_weight is not None else style.font_weight,
                italic=run.italic if run.italic is not None else style.italic,
                color=run.color or color,
                letter_spacing_pt=(
                    run.letter_spacing_pt
                    if run.letter_spacing_pt is not None
                    else style.letter_spacing_pt
                ),
            )
        )
    return tuple(out)


def _scale_runs(
    runs: tuple[ResolvedRun, ...], scale: float, out_text: str | None
) -> tuple[ResolvedRun, ...]:
    if out_text is not None:
        # Truncation collapses to a single run carrying the trimmed text in the lead style.
        lead = runs[0]
        return (
            lead.model_copy(
                update={"text": out_text, "font_size_pt": lead.font_size_pt * scale}
            ),
        )
    if scale == 1.0:
        return runs
    return tuple(r.model_copy(update={"font_size_pt": r.font_size_pt * scale}) for r in runs)


def _resolve_dir(paragraph_dir: str, text: str, group_dir: str) -> str:
    if paragraph_dir in ("ltr", "rtl"):
        return paragraph_dir
    strong = _first_strong_dir(text)
    return strong if strong is not None else group_dir


def _first_strong_dir(text: str) -> str | None:
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in ("R", "AL"):
            return "rtl"
        if bidi == "L":
            return "ltr"
    return None


def _missing_glyph_diag(
    node: CompiledText, codepoint: int, families: tuple[str, ...]
) -> Diagnostic:
    chain = ", ".join(families) if families else "(node default)"
    return diagnostic(
        "ARC-RND-011",
        f"Text node {node.id!r} has no glyph for U+{codepoint:04X} "
        f"({unicodedata.name(chr(codepoint), 'unknown')}) in any bundled font",
        severity="warning",
        hint=f"Add a font covering it under library-seed/fonts. Tried: {chain}, then fallback.",
        **_loc(node),
    )

"""Anchor layout solver v0.

Resolves each node's geometry by absolute positioning inside its parent. A node's position
comes from exactly one horizontal anchor (``left``/``right``/``center_x``) and one vertical
anchor (``top``/``bottom``/``center_y``); its size comes from width/height size specs
(``fixed``/``percent``/``fill``/``fit_content``). Under- or over-constrained nodes produce a
located ``ARC-LAY`` diagnostic naming the node. The input compiled document is never mutated;
a fresh :class:`LayoutDocument` is returned. Final geometry is normalized to 1/1024 pt to
avoid floating-point drift.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from arcavex.kernel.contracts.spi import LayoutSolver
from arcavex.kernel.contracts.types import MeasureFn, MeasureRequest
from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.kernel.ir.models import (
    CompiledDocument,
    CompiledGroup,
    CompiledImage,
    CompiledNode,
    CompiledShape,
    CompiledText,
    Constraints,
    LayoutDocument,
    LayoutNode,
    ResolvedCanvas,
    ResolvedContent,
    ResolvedImage,
    ResolvedShape,
    ResolvedText,
)
from arcavex.kernel.ir.units import Matrix3, Rect

_QUANT = 1024.0


def _q(value: float) -> float:
    return round(value * _QUANT) / _QUANT


class AnchorLayoutSolver(LayoutSolver):
    """Absolute anchor-based layout solver."""

    name: ClassVar[str] = "anchors"

    def solve(self, doc: CompiledDocument, measure: MeasureFn) -> LayoutDocument:
        """Resolve geometry for every node into a new layout document."""
        canvas_rect = Rect(0.0, 0.0, doc.canvas.width_pt, doc.canvas.height_pt)
        root = self._solve_node(doc.root, canvas_rect, measure)
        return LayoutDocument(
            canvas=ResolvedCanvas(
                width_pt=doc.canvas.width_pt,
                height_pt=doc.canvas.height_pt,
                dpi=doc.canvas.dpi,
            ),
            seed=doc.seed,
            root=root,
        )

    # ------------------------------------------------------------------ internals
    def _solve_node(
        self, node: CompiledNode, parent: Rect, measure: MeasureFn
    ) -> LayoutNode:
        width = self._resolve_width(node, parent, measure)
        height = self._resolve_height(node, parent, width, measure)
        x = self._resolve_x(node, parent, width)
        y = self._resolve_y(node, parent, height)

        tx, ty = node.transform.translate
        bounds = Rect(_q(x + tx), _q(y + ty), _q(width), _q(height))

        children: tuple[LayoutNode, ...] = ()
        clip = False
        if isinstance(node, CompiledGroup):
            clip = node.clip
            ordered = sorted(enumerate(node.children), key=lambda pair: (pair[1].z, pair[0]))
            children = tuple(self._solve_node(child, bounds, measure) for _, child in ordered)

        return LayoutNode(
            source_node_id=node.id,
            kind=node.type,
            bounds=bounds,
            absolute_transform=Matrix3.identity(),
            paint_bounds=bounds,
            overflow="none",
            opacity=node.style.opacity,
            visible=node.visible,
            clip=clip,
            resolved_content=self._resolve_content(node),
            children=children,
            source=node.source,
        )

    def _resolve_content(self, node: CompiledNode) -> ResolvedContent:
        if isinstance(node, CompiledText):
            return ResolvedText(
                text=node.text,
                font_families=node.style.font_families or ("Inter",),
                font_size_pt=node.style.font_size_pt or 16.0,
                font_weight=node.style.font_weight,
                italic=node.style.italic,
                color=node.style.text_color or (0.0, 0.0, 0.0, 1.0),
                align=node.style.align,
                direction=node.style.direction,
                line_height=node.style.line_height,
                letter_spacing_pt=node.style.letter_spacing_pt,
            )
        if isinstance(node, CompiledImage):
            return ResolvedImage(asset_path=node.asset_path, fit=node.fit)
        if isinstance(node, CompiledShape):
            return ResolvedShape(
                shape=node.shape,
                fill=node.style.fill,
                stroke=node.style.stroke,
                stroke_width_pt=node.style.stroke_width_pt,
                corner_radius_pt=node.style.corner_radius_pt,
            )
        return None

    def _resolve_width(self, node: CompiledNode, parent: Rect, measure: MeasureFn) -> float:
        spec = node.constraints.width
        if spec.mode == "fixed":
            return float(spec.value_pt or 0.0)
        if spec.mode == "percent":
            return parent.w * float(spec.percent or 0.0) / 100.0
        if spec.mode == "fill":
            return parent.w
        # fit_content
        return self._measure_node(node, None, measure).width_pt

    def _resolve_height(
        self, node: CompiledNode, parent: Rect, width: float, measure: MeasureFn
    ) -> float:
        spec = node.constraints.height
        if spec.mode == "fixed":
            return float(spec.value_pt or 0.0)
        if spec.mode == "percent":
            return parent.h * float(spec.percent or 0.0) / 100.0
        if spec.mode == "fill":
            return parent.h
        # fit_content
        return self._measure_node(node, width, measure).height_pt

    def _measure_node(  # noqa: ANN202
        self, node: CompiledNode, width: float | None, measure: MeasureFn
    ):
        if not isinstance(node, CompiledText):
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-020",
                    f"Node {node.id!r} uses 'fit_content' but is not a text node",
                    hint="Only text nodes support fit_content in Phase 0.",
                    **self._loc(node),
                )
            )
        req = MeasureRequest(
            text=node.text,
            font_families=node.style.font_families or ("Inter",),
            font_size_pt=node.style.font_size_pt or 16.0,
            font_weight=node.style.font_weight,
            italic=node.style.italic,
            letter_spacing_pt=node.style.letter_spacing_pt,
            line_height=node.style.line_height,
            direction=node.style.direction,
            max_width_pt=width,
        )
        return measure(req)

    @staticmethod
    def _loc(node: CompiledNode) -> dict[str, str | int | None]:
        """Return located-diagnostic kwargs from a node's carried source (RR-3)."""
        src = node.source
        if src is None:
            return {}
        return {"file": src.file, "keypath": src.keypath, "line": src.line}

    def _resolve_x(self, node: CompiledNode, parent: Rect, width: float) -> float:
        anchors = node.constraints.anchors
        present = [k for k in ("left", "right", "center_x") if k in anchors]
        self._require_single(node, present, "horizontal", node.constraints)
        key = present[0]
        anchor = anchors[key]
        ref = self._parent_edge(anchor.edge, parent, node) + anchor.offset_pt
        if key == "left":
            return ref
        if key == "right":
            return ref - width
        return ref - width / 2.0

    def _resolve_y(self, node: CompiledNode, parent: Rect, height: float) -> float:
        anchors = node.constraints.anchors
        present = [k for k in ("top", "bottom", "center_y") if k in anchors]
        self._require_single(node, present, "vertical", node.constraints)
        key = present[0]
        anchor = anchors[key]
        ref = self._parent_edge(anchor.edge, parent, node) + anchor.offset_pt
        if key == "top":
            return ref
        if key == "bottom":
            return ref - height
        return ref - height / 2.0

    def _require_single(
        self, node: CompiledNode, present: Sequence[str], axis: str, constraints: Constraints
    ) -> None:
        options = "left/right/center_x" if axis == "horizontal" else "top/bottom/center_y"
        if len(present) == 0:
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-030",
                    f"Node {node.id!r} is under-constrained on the {axis} axis",
                    hint=f"Add exactly one {axis} anchor ({options}).",
                    **self._loc(node),
                )
            )
        if len(present) > 1:
            joined = ", ".join(present)
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-031",
                    f"Node {node.id!r} is over-constrained on the {axis} axis: {joined}",
                    hint=f"Keep exactly one {axis} anchor; size comes from the size spec.",
                    **self._loc(node),
                )
            )

    def _parent_edge(self, edge: str, parent: Rect, node: CompiledNode) -> float:
        if edge == "top":
            return parent.y
        if edge == "bottom":
            return parent.bottom
        if edge == "center_y":
            return parent.center_y
        if edge == "left":
            return parent.x
        if edge == "right":
            return parent.right
        if edge == "center_x":
            return parent.center_x
        # The compiler only emits the six physical parent edges; anything else (e.g. the
        # logical start/end the model admits for future phases) is a real error, not silently
        # resolved to the centre.
        raise DiagnosticError(
            diagnostic(
                "ARC-LAY-014",
                f"Unsupported anchor edge {edge!r}",
                hint="Phase 0 supports top, bottom, left, right, center_x, and center_y.",
                **self._loc(node),
            )
        )

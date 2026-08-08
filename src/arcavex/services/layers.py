"""Authoritative layer-tree composition over authoring, compiler, and layout contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from arcavex.kernel.api import (
    CompilerProtocol,
    HitCandidate,
    HitTestReport,
    LayerEffect,
    LayerMask,
    LayerNodeReport,
    LayerSource,
    LayerTreeReport,
    OverflowReport,
    ProjectUIMetadata,
)
from arcavex.kernel.contracts.spi import LayoutSolver, MeasureFn
from arcavex.kernel.diagnostics import has_errors
from arcavex.kernel.ir.models import CompiledGroup, CompiledNode, LayoutNode
from arcavex.services.authoring import AuthoredLayer, AuthoringService

LayerTreeMode = Literal["authored", "rendered"]


@dataclass(frozen=True)
class _ResolvedLayer:
    compiled: CompiledNode
    layout: LayoutNode
    parent_id: str | None
    paint_index: int


class LayerService:
    """Compose desktop reports without re-evaluating a template scene."""

    def __init__(
        self,
        compiler: CompilerProtocol,
        solver: LayoutSolver,
        measure: MeasureFn,
        authoring: AuthoringService,
    ) -> None:
        self._compiler = compiler
        self._solver = solver
        self._measure = measure
        self._authoring = authoring

    def layer_tree(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        mode: LayerTreeMode,
        metadata: ProjectUIMetadata,
        *,
        project_patch: list[Any] | None = None,
        project_patch_file: Path | None = None,
    ) -> LayerTreeReport:
        """Compile/layout once, then correlate that result with source definitions."""
        authored_root = self._authoring.authored_layer_tree(template)
        compiled_result = self._compiler.compile(
            template,
            data,
            format_name,
            locale,
            style,
            project_patch=project_patch,
            project_patch_file=project_patch_file,
        )
        diagnostics = list(compiled_result.diagnostics)
        if compiled_result.document is None or has_errors(diagnostics):
            root = None
            if mode == "authored" and authored_root is not None:
                root = _build_authored_node(
                    authored_root,
                    {},
                    metadata,
                    0,
                    structural_ancestor=False,
                    ancestor_visible=True,
                    ancestor_locked=False,
                )
            return LayerTreeReport(
                ok=False,
                mode=mode,
                format=compiled_result.format_name or format_name,
                locale=locale,
                root=root,
                diagnostics=diagnostics,
            )
        layout = self._solver.solve(compiled_result.document, self._measure)
        diagnostics.extend(layout.warnings)
        dpi = compiled_result.document.canvas.dpi
        authored_by_id = _index_authored(authored_root)
        resolved_by_authored: dict[str, list[_ResolvedLayer]] = {}
        _index_resolved(
            compiled_result.document.root,
            layout.root,
            parent_id=None,
            paint_index=0,
            by_authored=resolved_by_authored,
        )
        if mode == "authored":
            root = (
                None
                if authored_root is None
                else _build_authored_node(
                    authored_root,
                    resolved_by_authored,
                    metadata,
                    dpi,
                    structural_ancestor=False,
                    ancestor_visible=True,
                    ancestor_locked=False,
                )
            )
        else:
            root = _build_rendered_node(
                compiled_result.document.root,
                layout.root,
                authored_by_id,
                metadata,
                dpi,
                parent_id=None,
                paint_index=0,
                ancestor_visible=True,
                ancestor_locked=False,
            )
        canvas = compiled_result.document.canvas
        return LayerTreeReport(
            ok=not has_errors(diagnostics),
            mode=mode,
            format=compiled_result.format_name or format_name,
            locale=locale,
            canvas_pt=(canvas.width_pt, canvas.height_pt),
            canvas_px=(canvas.width_px, canvas.height_px),
            dpi=dpi,
            root=root,
            diagnostics=diagnostics,
        )

    def hit_test(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        metadata: ProjectUIMetadata,
        point_pt: tuple[float, float],
        *,
        project_patch: list[Any] | None = None,
        project_patch_file: Path | None = None,
    ) -> HitTestReport:
        """Return rendered containment candidates in recursive reverse paint order."""
        tree = self.layer_tree(
            template,
            data,
            format_name,
            locale,
            style,
            "rendered",
            metadata,
            project_patch=project_patch,
            project_patch_file=project_patch_file,
        )
        candidates: list[HitCandidate] = []
        if tree.root is not None:
            _collect_hits(tree.root, point_pt, candidates)
        scale = tree.dpi / 72.0 if tree.dpi > 0 else None
        return HitTestReport(
            ok=tree.ok,
            format=tree.format,
            locale=tree.locale,
            point_pt=point_pt,
            point_px=None if scale is None else (point_pt[0] * scale, point_pt[1] * scale),
            candidates=candidates,
            diagnostics=list(tree.diagnostics),
        )


def _index_authored(root: AuthoredLayer | None) -> dict[str, AuthoredLayer]:
    indexed: dict[str, AuthoredLayer] = {}

    def visit(node: AuthoredLayer) -> None:
        indexed[node.id] = node
        for child in node.children:
            visit(child)

    if root is not None:
        visit(root)
    return indexed


def _authored_id(compiled: CompiledNode) -> str:
    """Read explicit compiler provenance, with compatibility for hand-built IR fixtures."""
    return compiled.authored_node_id or compiled.id


def _index_resolved(
    compiled: CompiledNode,
    layout: LayoutNode,
    *,
    parent_id: str | None,
    paint_index: int,
    by_authored: dict[str, list[_ResolvedLayer]],
) -> None:
    by_authored.setdefault(_authored_id(compiled), []).append(
        _ResolvedLayer(compiled, layout, parent_id, paint_index)
    )
    if not isinstance(compiled, CompiledGroup):
        return
    compiled_children = {child.id: child for child in compiled.children}
    for index, child_layout in enumerate(layout.children):
        child_compiled = compiled_children[child_layout.source_node_id]
        _index_resolved(
            child_compiled,
            child_layout,
            parent_id=layout.source_node_id,
            paint_index=index,
            by_authored=by_authored,
        )


def _build_authored_node(
    authored: AuthoredLayer,
    resolved_by_authored: dict[str, list[_ResolvedLayer]],
    metadata: ProjectUIMetadata,
    dpi: int,
    *,
    structural_ancestor: bool,
    ancestor_visible: bool,
    ancestor_locked: bool,
) -> LayerNodeReport:
    matches = resolved_by_authored.get(authored.id, [])
    structural = structural_ancestor or authored.origin != "static"
    resolved = matches[0] if not structural and len(matches) == 1 else None
    compiled = None if resolved is None else resolved.compiled
    layout = None if resolved is None else resolved.layout
    ui = metadata.layers.get(authored.id)
    locked = ancestor_locked or (False if ui is None else ui.locked)
    local_visible = authored.visible if layout is None else layout.visible
    visible = ancestor_visible and local_visible
    effects = _effects(compiled, authored)
    mask = _mask(compiled, authored)
    real_children = [
        _build_authored_node(
            child,
            resolved_by_authored,
            metadata,
            dpi,
            structural_ancestor=structural,
            ancestor_visible=visible,
            ancestor_locked=locked,
        )
        for child in sorted(
            authored.children,
            key=lambda child: (child.z, child.authored_index),
            reverse=True,
        )
    ]
    source = LayerSource(file=authored.file, keypath=authored.keypath, line=authored.line)
    node = LayerNodeReport(
        id=authored.id,
        authored_id=authored.id,
        instance_id=None if compiled is None else compiled.id,
        parent_id=authored.parent_id,
        authored_index=authored.authored_index,
        paint_index=None if resolved is None else resolved.paint_index,
        z=authored.z if compiled is None else compiled.z,
        kind=cast(Any, authored.kind),
        origin=cast(Any, authored.origin),
        condition=authored.condition,
        collection=authored.collection,
        loop_var=authored.loop_var,
        key=authored.key,
        display_name=authored.id if ui is None or ui.display_name is None else ui.display_name,
        visible=visible,
        locked=locked,
        color=None if ui is None else ui.color,
        editable=not locked,
        hit_testable=layout is not None and visible,
        bounds_pt=None if layout is None else _rect(layout.bounds),
        bounds_px=None if layout is None else _rect_px(layout.bounds, dpi),
        paint_bounds_pt=None if layout is None else _rect(layout.paint_bounds),
        paint_bounds_px=None if layout is None else _rect_px(layout.paint_bounds, dpi),
        absolute_transform=None if layout is None else _matrix(layout),
        rotate_deg=0.0 if layout is None else layout.rotate_deg,
        overflow=None if layout is None else _overflow(layout),
        source=source,
        effects=effects,
        mask=mask,
        children=[],
    )
    return node.model_copy(
        update={"children": [*real_children, *_virtual_rows(node, len(real_children))]}
    )


def _build_rendered_node(
    compiled: CompiledNode,
    layout: LayoutNode,
    authored_by_id: dict[str, AuthoredLayer],
    metadata: ProjectUIMetadata,
    dpi: int,
    *,
    parent_id: str | None,
    paint_index: int,
    ancestor_visible: bool,
    ancestor_locked: bool,
) -> LayerNodeReport:
    authored_id = _authored_id(compiled)
    authored = authored_by_id.get(authored_id)
    ui = metadata.layers.get(authored_id)
    locked = ancestor_locked or (False if ui is None else ui.locked)
    visible = ancestor_visible and layout.visible
    source = (
        _source_from_layout(layout)
        if authored is None
        else LayerSource(file=authored.file, keypath=authored.keypath, line=authored.line)
    )
    real_children: list[LayerNodeReport] = []
    if isinstance(compiled, CompiledGroup):
        compiled_children = {child.id: child for child in compiled.children}
        for index in range(len(layout.children) - 1, -1, -1):
            child_layout = layout.children[index]
            child_compiled = compiled_children[child_layout.source_node_id]
            real_children.append(
                _build_rendered_node(
                    child_compiled,
                    child_layout,
                    authored_by_id,
                    metadata,
                    dpi,
                    parent_id=compiled.id,
                    paint_index=index,
                    ancestor_visible=visible,
                    ancestor_locked=locked,
                )
            )
    node = LayerNodeReport(
        id=compiled.id,
        authored_id=authored_id,
        instance_id=compiled.id,
        parent_id=parent_id,
        authored_index=0 if authored is None else authored.authored_index,
        paint_index=paint_index,
        z=compiled.z,
        kind=layout.kind,
        origin="static" if authored is None else cast(Any, authored.origin),
        condition=None if authored is None else authored.condition,
        collection=None if authored is None else authored.collection,
        loop_var=None if authored is None else authored.loop_var,
        key=None if authored is None else authored.key,
        display_name=authored_id if ui is None or ui.display_name is None else ui.display_name,
        visible=visible,
        locked=locked,
        color=None if ui is None else ui.color,
        editable=not locked,
        hit_testable=visible,
        bounds_pt=_rect(layout.bounds),
        bounds_px=_rect_px(layout.bounds, dpi),
        paint_bounds_pt=_rect(layout.paint_bounds),
        paint_bounds_px=_rect_px(layout.paint_bounds, dpi),
        absolute_transform=_matrix(layout),
        rotate_deg=layout.rotate_deg,
        overflow=_overflow(layout),
        source=source,
        effects=_resolved_effects(compiled),
        mask=_resolved_mask(compiled),
        children=[],
    )
    return node.model_copy(
        update={"children": [*real_children, *_virtual_rows(node, len(real_children))]}
    )


def _resolved_effects(compiled: CompiledNode) -> list[LayerEffect]:
    return [
        LayerEffect(index=index, name=effect.name, category=effect.category, params=effect.params)
        for index, effect in enumerate(compiled.effects)
    ]


def _effects(compiled: CompiledNode | None, authored: AuthoredLayer) -> list[LayerEffect]:
    if compiled is not None:
        return _resolved_effects(compiled)
    return [
        LayerEffect(index=index, name=effect.name, params=effect.params)
        for index, effect in enumerate(authored.effects)
    ]


def _resolved_mask(compiled: CompiledNode) -> LayerMask | None:
    if compiled.mask is None:
        return None
    return LayerMask(component=compiled.mask.component, params=compiled.mask.params)


def _mask(compiled: CompiledNode | None, authored: AuthoredLayer) -> LayerMask | None:
    if compiled is not None:
        return _resolved_mask(compiled)
    if authored.mask is None:
        return None
    return LayerMask(component=authored.mask.component, params=authored.mask.params)


def _virtual_rows(owner: LayerNodeReport, authored_index: int) -> list[LayerNodeReport]:
    rows: list[LayerNodeReport] = []
    if owner.mask is not None:
        rows.append(
            LayerNodeReport(
                id=f"{owner.id}::mask",
                authored_id=owner.authored_id,
                instance_id=owner.instance_id,
                parent_id=owner.id,
                authored_index=authored_index,
                z=owner.z,
                kind="mask",
                origin=owner.origin,
                display_name=f"Mask: {owner.mask.component}",
                visible=True,
                locked=owner.locked,
                color=owner.color,
                editable=False,
                hit_testable=False,
                virtual=True,
                source=owner.source,
                mask=owner.mask,
            )
        )
        authored_index += 1
    for effect in owner.effects:
        rows.append(
            LayerNodeReport(
                id=f"{owner.id}::effect:{effect.index}",
                authored_id=owner.authored_id,
                instance_id=owner.instance_id,
                parent_id=owner.id,
                authored_index=authored_index,
                z=owner.z,
                kind="effect",
                origin=owner.origin,
                display_name=f"Effect: {effect.name}",
                visible=True,
                locked=owner.locked,
                color=owner.color,
                editable=False,
                hit_testable=False,
                virtual=True,
                source=owner.source,
                effects=[effect],
            )
        )
        authored_index += 1
    return rows


def _collect_hits(
    node: LayerNodeReport,
    point_pt: tuple[float, float],
    candidates: list[HitCandidate],
) -> None:
    """Traverse presentation children first: this is recursive reverse paint order."""
    if node.virtual:
        return
    for child in node.children:
        _collect_hits(child, point_pt, candidates)
    if (
        not node.hit_testable
        or not node.visible
        or node.instance_id is None
        or node.bounds_pt is None
        or node.paint_bounds_pt is None
        or not _contains(node.paint_bounds_pt, point_pt)
    ):
        return
    candidates.append(
        HitCandidate(
            id=node.id,
            authored_id=node.authored_id,
            instance_id=node.instance_id,
            parent_id=node.parent_id,
            kind=cast(Any, node.kind),
            display_name=node.display_name,
            editable=node.editable,
            locked=node.locked,
            bounds_pt=node.bounds_pt,
            paint_bounds_pt=node.paint_bounds_pt,
        )
    )


def _contains(
    bounds: tuple[float, float, float, float], point: tuple[float, float]
) -> bool:
    x, y, width, height = bounds
    return x <= point[0] <= x + width and y <= point[1] <= y + height


def _rect(rect: Any) -> tuple[float, float, float, float]:
    return (rect.x, rect.y, rect.w, rect.h)


def _rect_px(rect: Any, dpi: int) -> tuple[float, float, float, float]:
    scale = dpi / 72.0
    return (rect.x * scale, rect.y * scale, rect.w * scale, rect.h * scale)


def _matrix(layout: LayoutNode) -> tuple[float, float, float, float, float, float]:
    transform = layout.absolute_transform
    return (transform.a, transform.b, transform.c, transform.d, transform.e, transform.f)


def _overflow(layout: LayoutNode) -> OverflowReport | None:
    overflow = layout.overflow
    if overflow.kind == "none":
        return None
    return OverflowReport(
        kind=overflow.kind,
        measured_w_pt=overflow.measured_w_pt,
        measured_h_pt=overflow.measured_h_pt,
        box_w_pt=overflow.box_w_pt,
        box_h_pt=overflow.box_h_pt,
    )


def _source_from_layout(layout: LayoutNode) -> LayerSource | None:
    source = layout.source
    if source is None:
        return None
    return LayerSource(file=source.file, keypath=source.keypath, line=source.line)

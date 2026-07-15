"""Effect-plan compilation: the linear authored list becomes a category-aware plan.

The authoring model is a flat ordered ``effects:`` list; the renderer compiles it into
``geometry -> fused color -> ordered raster -> composite`` (spec §4.4). This module owns that
compilation and, crucially, the *fusion*: a run of consecutive color matrices collapses into a
single matrix (real associative composition, see
:func:`~arcavex.builtin.effects_core.context.compose_color_matrices`), and the whole color
stage becomes one composed Skia color filter applied in a single pass. Fusion is provably
equivalent to sequential application, and the resulting plan is inspectable
(:attr:`EffectPlan.color_ops`) so a test can assert the collapse actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import skia  # type: ignore[import-untyped]
from pydantic import BaseModel

from arcavex.builtin.effects_core.context import (
    ColorContext,
    ColorMatrix,
    ColorTable,
    ColorTransform,
    compose_color_matrices,
)
from arcavex.kernel.contracts.spi import Effect
from arcavex.kernel.contracts.types import EffectKind
from arcavex.kernel.ir.models import EffectSpec


@dataclass(frozen=True)
class PlannedEffect:
    """One resolved effect: its implementation, validated params, and authored index.

    ``index`` is the effect's position in the node's original authored list; it seeds the
    per-effect RNG (spec §3.2), so it stays fixed regardless of category reordering.
    """

    effect: Effect
    params: BaseModel
    index: int


@dataclass(frozen=True)
class EffectPlan:
    """The category-aware execution plan for one node's effects.

    ``color_ops`` is the *fused* color stage (adjacent matrices already collapsed); building the
    Skia filter from it is one composed application. Empty plans are cheap: a node with no
    effects yields an all-empty plan and the renderer takes its fast path.
    """

    geometry: list[PlannedEffect] = field(default_factory=list)
    color_ops: list[ColorTransform] = field(default_factory=list)
    raster: list[PlannedEffect] = field(default_factory=list)
    composite: list[PlannedEffect] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Whether the plan does nothing (no effects on the node)."""
        return not (self.geometry or self.color_ops or self.raster or self.composite)


def compile_effect_plan(
    specs: tuple[EffectSpec, ...], effects: dict[str, Effect]
) -> EffectPlan:
    """Compile a node's authored effect list into a category-aware, color-fused plan.

    The registry has already been checked at compile time (unknown names/params are located
    errors), so this trusts the specs and only rebuilds each param model. Category reordering is
    stable within a category, matching the authored order.
    """
    geometry: list[PlannedEffect] = []
    color: list[tuple[PlannedEffect, ColorTransform]] = []
    raster: list[PlannedEffect] = []
    composite: list[PlannedEffect] = []

    for index, spec in enumerate(specs):
        effect = effects[spec.name]
        params = effect.param_schema(**spec.params)
        planned = PlannedEffect(effect=effect, params=params, index=index)
        if effect.kind is EffectKind.GEOMETRY:
            geometry.append(planned)
        elif effect.kind is EffectKind.COLOR:
            transform = effect.apply(ColorContext(params))
            assert isinstance(transform, (ColorMatrix, ColorTable))
            color.append((planned, transform))
        elif effect.kind is EffectKind.RASTER:
            raster.append(planned)
        else:
            composite.append(planned)

    return EffectPlan(
        geometry=geometry,
        color_ops=_fuse_colors([t for _, t in color]),
        raster=raster,
        composite=composite,
    )


def _fuse_colors(transforms: list[ColorTransform]) -> list[ColorTransform]:
    """Collapse each maximal run of consecutive matrices into one matrix (the fusion step)."""
    fused: list[ColorTransform] = []
    for transform in transforms:
        if isinstance(transform, ColorMatrix) and fused and isinstance(fused[-1], ColorMatrix):
            fused[-1] = compose_color_matrices(fused[-1], transform)
        else:
            fused.append(transform)
    return fused


def build_color_filter(color_ops: list[ColorTransform]) -> skia.ColorFilter | None:
    """Compose the fused color ops into a single Skia color filter (one application).

    Filters compose so the first authored op runs first: ``Compose(later, earlier)`` evaluates
    ``earlier`` then ``later``. Returns ``None`` when there is no color stage.
    """
    if not color_ops:
        return None
    result: skia.ColorFilter | None = None
    for op in color_ops:
        current = _skia_color_filter(op)
        result = current if result is None else skia.ColorFilters.Compose(current, result)
    return result


def _skia_color_filter(op: ColorTransform) -> skia.ColorFilter:
    if isinstance(op, ColorMatrix):
        return skia.ColorFilters.Matrix(list(op.m))
    return skia.TableColorFilter.MakeARGB(list(op.a), list(op.r), list(op.g), list(op.b))

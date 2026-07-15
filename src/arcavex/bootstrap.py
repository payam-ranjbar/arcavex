"""Application composition root.

This is the only module that knows both the kernel and the built-in implementations. It
constructs the registries, registers built-ins, builds shared services, and returns the
wired :class:`~arcavex.kernel.api.Facade`. The pure kernel imports nothing from here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from arcavex.builtin.backend_skia import SkiaBackend
from arcavex.builtin.effects_core import builtin_effects
from arcavex.builtin.export_raster import PngExporter
from arcavex.builtin.layout_anchors import AnchorLayoutSolver
from arcavex.builtin.masks_core import builtin_masks
from arcavex.builtin.shapes_core import builtin_shapes
from arcavex.builtin.template_fns import builtin_template_functions
from arcavex.kernel.api import Facade
from arcavex.kernel.contracts.spi import Effect, MaskGenerator, ShapeGenerator
from arcavex.kernel.registry import Registries
from arcavex.services.authoring import AuthoringService
from arcavex.services.doctor import engine_version, run_doctor
from arcavex.services.explain import explain_code
from arcavex.services.library import Library
from arcavex.services.orchestrator import Orchestrator
from arcavex.services.pipeline import render_to_file
from arcavex.services.projects import ProjectService
from arcavex.services.runs import RunStore
from arcavex.services.style import StyleResolver
from arcavex.services.template import Compiler
from arcavex.services.template.expressions import FunctionTable, UnknownFunctionError, Value
from arcavex.services.text import TextService


def build_registries(text_service: TextService) -> Registries:
    """Create registries and register all built-in components."""
    registries = Registries()
    for mask in builtin_masks():
        registries.masks.register(mask.name, mask)
    for name, effect in builtin_effects().items():
        registries.effects.register(name, effect)
    for shape in builtin_shapes():
        registries.shapes.register(shape.name, shape)
    effect_map = _effect_map(registries)
    shape_map = _shape_map(registries)
    # The solver grows paint_bounds from effect declarations; the backend applies effects and
    # builds shape-generator paths. Both resolve only through the registry (spec §4.4).
    registries.layouts.register("anchors", AnchorLayoutSolver(effect_map))
    registries.backends.register(
        "skia", SkiaBackend(text_service, _mask_map(registries), effect_map, shape_map)
    )
    registries.exporters.register("png", PngExporter())
    for fn in builtin_template_functions():
        registries.template_fns.register(fn.name, fn)
    return registries


def _mask_map(registries: Registries) -> dict[str, MaskGenerator]:
    """Materialize the mask registry as a name -> generator dict for the backend."""
    return {name: registries.masks.get(name) for name in registries.masks.names()}


def _effect_map(registries: Registries) -> dict[str, Effect]:
    """Materialize the effect registry as a name -> effect dict for the solver/backend."""
    return {name: registries.effects.get(name) for name in registries.effects.names()}


def _shape_map(registries: Registries) -> dict[str, ShapeGenerator]:
    """Materialize the shape registry as a name -> generator dict for the backend."""
    return {name: registries.shapes.get(name) for name in registries.shapes.names()}


def build_function_table(registries: Registries) -> FunctionTable:
    """Build the expression function table that resolves through the registry.

    This is the composition-root wiring that keeps the kernel and services import-clean: the
    evaluator (a service) calls functions only through this injected table, and the table
    resolves each name against the ``TemplateFunction`` registry populated with built-ins.
    """

    def table(name: str, args: list[Value]) -> Value:
        if not registries.template_fns.has(name):
            raise UnknownFunctionError(name, registries.template_fns.names())
        return registries.template_fns.get(name).call(*args)

    return table


def build_facade(font_dirs: list[Path] | None = None) -> Facade:
    """Build and return the fully wired service facade.

    Args:
        font_dirs: Optional explicit bundled-font directories (defaults resolved by the
            text service).

    Returns:
        The composed :class:`Facade`.
    """
    text_service = TextService(font_dirs)
    registries = build_registries(text_service)
    mask_names = frozenset(registries.masks.names())

    def mask_schema(name: str) -> type[BaseModel] | None:
        return registries.masks.get(name).param_schema if registries.masks.has(name) else None

    def effect_schema(name: str) -> type[BaseModel] | None:
        return registries.effects.get(name).param_schema if registries.effects.has(name) else None

    def effect_kind(name: str) -> str | None:
        return registries.effects.get(name).kind.value if registries.effects.has(name) else None

    def shape_schema(name: str) -> type[BaseModel] | None:
        return registries.shapes.get(name).param_schema if registries.shapes.has(name) else None

    style_resolver = StyleResolver()
    compiler = Compiler(
        available_fonts=frozenset(text_service.families),
        functions=build_function_table(registries),
        masks=mask_names,
        mask_schema=mask_schema,
        effects=frozenset(registries.effects.names()),
        effect_schema=effect_schema,
        effect_kind=effect_kind,
        shapes=frozenset(registries.shapes.names()),
        shape_schema=shape_schema,
        styles=style_resolver,
    )
    authoring = AuthoringService(compiler, registries.template_fns.names())
    orchestrator = _build_orchestrator(registries, compiler, text_service)
    return Facade(
        registries,
        compiler,
        text_service.measure,
        doctor_probe=lambda: run_doctor(text_service),
        explain_lookup=explain_code,
        authoring=authoring,
        style_provider=style_resolver,
        orchestrator=orchestrator,
    )


def _build_orchestrator(
    registries: Registries, compiler: Compiler, text_service: TextService
) -> Orchestrator:
    """Wire the project/provenance orchestrator over the shared render pipeline.

    The render function binds the registry's solver, backend, and exporter into the one
    layout→render→export tail (``services.pipeline``), so project renders and reruns share the
    exact byte-producing path with direct renders.
    """
    solver = registries.layouts.get("anchors")
    backend = registries.backends.get("skia")
    exporter = registries.exporters.get("png")

    def render_fn(
        document: object, output: Path, dpi: int | None, debug: bool
    ) -> object:
        return render_to_file(
            solver, backend, exporter, text_service.measure,
            document, output, dpi, debug,  # type: ignore[arg-type]
        )

    library = Library()
    return Orchestrator(
        compiler,
        render_fn,  # type: ignore[arg-type]
        engine_version(),
        library=library,
        projects=ProjectService(library),
        run_store=RunStore(),
        batch_worker=_batch_render_one,
    )


# A per-process facade cache: a batch worker process builds one engine and reuses it across the
# projects it is handed, so parallelism does not pay the font-database build cost per project.
_WORKER_FACADE: Facade | None = None


def _batch_render_one(payload: tuple[str, int | None]) -> dict[str, object]:
    """Render one project in a worker process and return a picklable result (spec §6.1.2).

    This module-level function is the process-pool entry point: it (re)builds a full engine in
    its own process — no state is shared with the parent or sibling jobs — so a parallel batch is
    output-identical to a serial one. Diagnostics are returned as plain dicts to cross the
    process boundary.
    """
    global _WORKER_FACADE
    if _WORKER_FACADE is None:
        _WORKER_FACADE = build_facade()
    project_dir, dpi = payload
    report = _WORKER_FACADE.render_project(project=Path(project_dir), dpi=dpi)
    return {
        "ok": report.ok,
        "run_id": report.run_id,
        "run_dir": report.run_dir,
        "outputs": list(report.outputs),
        "diagnostics": [d.model_dump(mode="json") for d in report.diagnostics],
    }

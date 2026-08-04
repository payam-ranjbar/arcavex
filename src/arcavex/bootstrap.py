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
from arcavex.builtin.export_pdf import PdfExporter
from arcavex.builtin.export_raster import JpegExporter, PngExporter, WebpExporter
from arcavex.builtin.layout_anchors import AnchorLayoutSolver
from arcavex.builtin.masks_core import builtin_masks
from arcavex.builtin.shapes_core import builtin_shapes
from arcavex.builtin.template_fns import builtin_template_functions
from arcavex.kernel.api import Facade
from arcavex.kernel.contracts.spi import Effect, MaskGenerator, ShapeGenerator
from arcavex.kernel.diagnostics import Diagnostic
from arcavex.kernel.registry import Registries
from arcavex.services.authoring import AuthoringService
from arcavex.services.budgets import RenderBudget
from arcavex.services.cache import DerivedImageCache
from arcavex.services.config import RuntimeConfig
from arcavex.services.doctor import engine_version, run_doctor
from arcavex.services.explain import explain_code
from arcavex.services.extensions import ExtensionService, load_enabled_extensions
from arcavex.services.fonts import FontService
from arcavex.services.library import Library
from arcavex.services.orchestrator import Orchestrator
from arcavex.services.pipeline import render_to_file
from arcavex.services.projects import ProjectService
from arcavex.services.runs import RunStore
from arcavex.services.skills import SkillService
from arcavex.services.style import StyleResolver
from arcavex.services.template import Compiler
from arcavex.services.template.expressions import FunctionTable, UnknownFunctionError, Value
from arcavex.services.text import TextService

# Default in-process byte budget for the derived-variant cache (spec §4.7); overridable via
# ``[cache].derived_bytes`` in config.toml.
_DEFAULT_CACHE_BYTES = 256_000_000


def build_registries(text_service: TextService) -> tuple[Registries, list[Diagnostic]]:
    """Create registries, register built-ins, then load enabled local extensions.

    Enabled extensions are loaded *after* the built-in effects/masks/shapes but *before* the
    solver and backend are constructed, because those snapshot the effect/mask/shape maps — so an
    extension component is in the pipeline maps exactly like a built-in (spec §3.3). Extension
    load problems (incompatibility, a name colliding with a built-in) are returned as diagnostics
    rather than raised, so a broken extension never wedges engine construction.
    """
    registries = Registries()
    for mask in builtin_masks():
        registries.masks.register(mask.name, mask)
    for name, effect in builtin_effects().items():
        registries.effects.register(name, effect)
    for shape in builtin_shapes():
        registries.shapes.register(shape.name, shape)
    registries.exporters.register("png", PngExporter())
    registries.exporters.register("jpeg", JpegExporter())
    registries.exporters.register("webp", WebpExporter())
    registries.exporters.register("pdf", PdfExporter())
    for fn in builtin_template_functions():
        registries.template_fns.register(fn.name, fn)
    # Load enabled extensions before the maps are snapshotted so their effects/masks/shapes feed
    # the backend and solver; "anchors"/"skia" are reserved by the loader so an extension cannot
    # pre-empt the built-in solver/backend registered just below.
    load_diagnostics = load_enabled_extensions(registries)
    effect_map = _effect_map(registries)
    shape_map = _shape_map(registries)
    # The solver grows paint_bounds from effect declarations; the backend applies effects and
    # builds shape-generator paths. Both resolve only through the registry (spec §4.4).
    registries.layouts.register("anchors", AnchorLayoutSolver(effect_map))
    cache_budget = RuntimeConfig.load().resolve_cache_bytes(_DEFAULT_CACHE_BYTES)
    image_cache = DerivedImageCache(byte_budget=cache_budget)
    registries.backends.register(
        "skia",
        SkiaBackend(text_service, _mask_map(registries), effect_map, shape_map, image_cache),
    )
    return registries, load_diagnostics


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
    registries, extension_load_diagnostics = build_registries(text_service)
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
    budget = RenderBudget.from_config(RuntimeConfig.load().raw)
    orchestrator = _build_orchestrator(registries, compiler, text_service, budget)
    return Facade(
        registries,
        compiler,
        text_service.measure,
        doctor_probe=lambda: run_doctor(text_service),
        explain_lookup=explain_code,
        authoring=authoring,
        style_provider=style_resolver,
        orchestrator=orchestrator,
        extensions=ExtensionService(builtin_names=_builtin_component_names()),
        extension_load_diagnostics=extension_load_diagnostics,
        # Font management resolves its directories on every call rather than capturing the ones
        # this engine loaded, so 'font add' always writes to the home currently in effect.
        fonts=FontService(),
        skills=SkillService(),
        budget=budget,
        engine_version=engine_version(),
    )


def _builtin_component_names() -> dict[str, frozenset[str]]:
    """Return the names each built-in occupies per component kind (spec §3.3 collision check).

    ``ext validate``/``add`` use this to reject an extension component that would shadow a
    built-in up front, naming both providers. Keyed by the component-kind keyword the manifest
    uses. ``layout_solver``/``backend`` carry the reserved built-in names the loader guards.
    """
    return {
        "effect": frozenset(builtin_effects()),
        "mask": frozenset(m.name for m in builtin_masks()),
        "shape": frozenset(s.name for s in builtin_shapes()),
        "exporter": frozenset({"png", "jpeg", "webp", "pdf"}),
        "template_function": frozenset(f.name for f in builtin_template_functions()),
        "layout_solver": frozenset({"anchors"}),
        "backend": frozenset({"skia"}),
        "decoder": frozenset(),
    }


def _build_orchestrator(
    registries: Registries,
    compiler: Compiler,
    text_service: TextService,
    budget: RenderBudget,
) -> Orchestrator:
    """Wire the project/provenance orchestrator over the shared render pipeline.

    The render function binds the registry's solver, backend, and exporter into the one
    layout→render→export tail (``services.pipeline``), so project renders and reruns share the
    exact byte-producing path with direct renders, including the per-render resource budgets.
    """
    solver = registries.layouts.get("anchors")
    backend = registries.backends.get("skia")
    exporter = registries.exporters.get("png")
    version = engine_version()

    def render_fn(
        document: object, output: Path, dpi: int | None, debug: bool
    ) -> object:
        return render_to_file(
            solver, backend, exporter, text_service.measure,
            document, output, dpi, debug,  # type: ignore[arg-type]
            budget, version,
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

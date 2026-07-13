"""Application composition root.

This is the only module that knows both the kernel and the built-in implementations. It
constructs the registries, registers built-ins, builds shared services, and returns the
wired :class:`~arcavex.kernel.api.Facade`. The pure kernel imports nothing from here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from arcavex.builtin.backend_skia import SkiaBackend
from arcavex.builtin.export_raster import PngExporter
from arcavex.builtin.layout_anchors import AnchorLayoutSolver
from arcavex.builtin.masks_core import builtin_masks
from arcavex.builtin.template_fns import builtin_template_functions
from arcavex.kernel.api import Facade
from arcavex.kernel.contracts.spi import MaskGenerator
from arcavex.kernel.registry import Registries
from arcavex.services.authoring import AuthoringService
from arcavex.services.doctor import run_doctor
from arcavex.services.explain import explain_code
from arcavex.services.template import Compiler
from arcavex.services.template.expressions import FunctionTable, UnknownFunctionError, Value
from arcavex.services.text import TextService


def build_registries(text_service: TextService) -> Registries:
    """Create registries and register all built-in components."""
    registries = Registries()
    for mask in builtin_masks():
        registries.masks.register(mask.name, mask)
    registries.layouts.register("anchors", AnchorLayoutSolver())
    registries.backends.register("skia", SkiaBackend(text_service, _mask_map(registries)))
    registries.exporters.register("png", PngExporter())
    for fn in builtin_template_functions():
        registries.template_fns.register(fn.name, fn)
    return registries


def _mask_map(registries: Registries) -> dict[str, MaskGenerator]:
    """Materialize the mask registry as a name -> generator dict for the backend."""
    return {name: registries.masks.get(name) for name in registries.masks.names()}


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

    compiler = Compiler(
        available_fonts=frozenset(text_service.families),
        functions=build_function_table(registries),
        masks=mask_names,
        mask_schema=mask_schema,
    )
    authoring = AuthoringService(compiler, registries.template_fns.names())
    return Facade(
        registries,
        compiler,
        text_service.measure,
        doctor_probe=lambda: run_doctor(text_service),
        explain_lookup=explain_code,
        authoring=authoring,
    )

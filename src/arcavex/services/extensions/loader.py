"""The local directory loader: import an extension's entry modules and register components.

This is a custom directory loader, not a Python entry-point mechanism (spec §3.3). At process
start :func:`load_enabled_extensions` reads the added-extension state, and for every *enabled*
extension it parses the manifest, checks engine/IR compatibility, imports each declared entry
module, instantiates the component class, and registers it into the same typed registry the
built-ins use — so a loaded component is indistinguishable from a built-in at the pipeline.

Trust boundary (spec §7.3): the entry modules are imported and their top-level code runs with the
full permissions of the Arcavex process. These are trusted local code; the loader validates for
compatibility, not for malice. A component that fails to load is skipped with a diagnostic rather
than crashing the engine, so one bad extension never wedges the others or the built-ins.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic
from arcavex.kernel.registry import Registries
from arcavex.sdk.registration import COMPONENT_KINDS, register_component

# The current engine and IR versions an extension declares its floors against.
from arcavex.services.doctor import engine_version
from arcavex.services.extensions.manifest import (
    ComponentSpec,
    ExtensionManifest,
    parse_manifest,
    version_at_least,
)
from arcavex.services.extensions.state import ExtensionState, source_path
from arcavex.services.orchestrator import IR_VERSION

# Built-in default pipeline component names an extension must not shadow. These are registered
# after extension load (they depend on maps built from the loaded effects), so the loader guards
# them explicitly; every other built-in name is already present and guarded by the registry.
_RESERVED_NAMES: dict[str, frozenset[str]] = {
    "layouts": frozenset({"anchors"}),
    "backends": frozenset({"skia"}),
}


def load_enabled_extensions(
    registries: Registries,
    *,
    env: dict[str, str] | None = None,
) -> list[Diagnostic]:
    """Load and register every enabled local extension into ``registries``.

    Returns accumulated diagnostics (compatibility failures, import errors, duplicate names). The
    caller (bootstrap) surfaces them; a diagnostic here never raises past this function, so engine
    construction always completes with the built-ins intact even if an extension is broken.
    """
    state = ExtensionState(env)
    diagnostics: list[Diagnostic] = []
    for record in state.records():
        if not record.enabled:
            continue
        ext_dir = source_path(record.name, env)
        diagnostics.extend(register_extension(registries, ext_dir))
    return diagnostics


def register_extension(registries: Registries, ext_dir: Path) -> list[Diagnostic]:
    """Parse, compat-check, import, and register one extension directory's components.

    Used by the loader for enabled extensions and by ``ext test``/validation to exercise the real
    registration path. Returns diagnostics; components that register cleanly take effect, and a
    component that collides or fails to import is reported and skipped.
    """
    manifest, diagnostics = parse_manifest(ext_dir)
    if manifest is None:
        return diagnostics
    compat = check_compatibility(manifest, ext_dir)
    if compat is not None:
        diagnostics.append(compat)
        return diagnostics
    package = _load_package(manifest.name, Path(ext_dir))
    for spec in manifest.components:
        diagnostics.extend(_register_one(registries, manifest, package, spec, ext_dir))
    return diagnostics


def check_compatibility(manifest: ExtensionManifest, ext_dir: Path) -> Diagnostic | None:
    """Return an ``ARC-EXT-020`` diagnostic if the manifest's engine/IR floors exceed this build."""
    engine = engine_version()
    problems: list[str] = []
    if not version_at_least(engine, manifest.engine_min):
        problems.append(f"needs engine >= {manifest.engine_min} (this engine is {engine})")
    if not version_at_least(IR_VERSION, manifest.ir_min):
        problems.append(f"needs IR >= {manifest.ir_min} (this IR is {IR_VERSION})")
    if not problems:
        return None
    return diagnostic(
        "ARC-EXT-020",
        f"Extension {manifest.name!r} is incompatible with this build: " + "; ".join(problems),
        file=str(ext_dir),
        hint="Upgrade Arcavex, or lower engine_min/ir_min if the extension truly supports this "
        "build.",
    )


def _register_one(
    registries: Registries,
    manifest: ExtensionManifest,
    package: str,
    spec: ComponentSpec,
    ext_dir: Path,
) -> list[Diagnostic]:
    kind = COMPONENT_KINDS[spec.kind]
    registry = getattr(registries, kind.registry_attr)
    reserved = _RESERVED_NAMES.get(kind.registry_attr, frozenset())
    if registry.has(spec.name) or spec.name in reserved:
        existing = "a built-in" if spec.name in reserved else type(registry.get(spec.name)).__name__
        return [
            diagnostic(
                "ARC-EXT-001",
                f"Duplicate {spec.kind} component {spec.name!r}: already provided by "
                f"{existing}, cannot also register {manifest.name!r}'s {spec.class_name}",
                file=str(ext_dir),
                hint="Component names are globally unique per kind; rename the extension's "
                "component.",
            )
        ]
    try:
        instance = instantiate_component(package, ext_dir, spec)
    except DiagnosticError as exc:
        return list(exc.diagnostics)
    try:
        register_component(registries, spec.kind, spec.name, instance)
    except DiagnosticError as exc:
        return list(exc.diagnostics)
    return []


def instantiate_component(package: str, ext_dir: Path, spec: ComponentSpec) -> object:
    """Import the entry module, fetch the class, and construct a component instance.

    Raises a :class:`DiagnosticError` (``ARC-EXT-021``) if the module or class cannot be imported
    or the class cannot be instantiated with no arguments.
    """
    module_name = f"{package}.{spec.module}"
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - any import failure is one located diagnostic
        raise DiagnosticError(
            diagnostic(
                "ARC-EXT-021",
                f"Could not import entry module {spec.module!r} of component {spec.name!r}: {exc}",
                file=str(ext_dir),
                hint="Check the module file exists in the extension directory and imports only "
                "the arcavex.sdk surface.",
            )
        ) from exc
    cls = getattr(module, spec.class_name, None)
    if cls is None:
        raise DiagnosticError(
            diagnostic(
                "ARC-EXT-021",
                f"Entry class {spec.class_name!r} not found in module {spec.module!r}",
                file=str(ext_dir),
                hint=f"Define class {spec.class_name} in {spec.module}.py, or fix the entry path.",
            )
        )
    try:
        return cls()
    except Exception as exc:  # noqa: BLE001 - construction failure is one located diagnostic
        raise DiagnosticError(
            diagnostic(
                "ARC-EXT-021",
                f"Component {spec.name!r} ({spec.class_name}) could not be constructed: {exc}",
                file=str(ext_dir),
                hint="A component class must be instantiable with no arguments.",
            )
        ) from exc


def _load_package(name: str, ext_dir: Path) -> str:
    """Register a synthetic package rooted at ``ext_dir`` so entry modules import in isolation.

    Each extension's modules load under a unique ``arcavex_ext_<name>`` package whose ``__path__``
    is the extension directory. Two extensions that both ship an ``effects.py`` therefore never
    collide in ``sys.modules``, and a multi-file extension uses relative imports between its
    modules.
    """
    package = "arcavex_ext_" + name.replace("-", "_")
    # Drop any previously-imported submodules of this package so a re-registered extension (a
    # re-add of updated code, or a fresh validate in a long-lived process) imports its current
    # source rather than a stale cached module.
    for cached in [m for m in sys.modules if m == package or m.startswith(package + ".")]:
        del sys.modules[cached]
    module = types.ModuleType(package)
    module.__path__ = [str(ext_dir)]  # type: ignore[attr-defined]
    module.__package__ = package
    sys.modules[package] = module
    return package


__all__ = [
    "check_compatibility",
    "instantiate_component",
    "load_enabled_extensions",
    "register_extension",
]

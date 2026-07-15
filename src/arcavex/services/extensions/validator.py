"""Extension validation: manifest, compatibility, imports, determinism, schema, and shaders.

Validation (spec §7.2) catches the ways a *trusted local* extension can be wrong before it is
enabled: a malformed manifest, an engine/IR mismatch, an import that reaches outside the SDK
surface, a non-deterministic API call that would break reproducible output, a parameter schema
that is not valid pydantic, or an SkSL shader that will not compile.

None of this is a security sandbox. The AST scans and the import of the entry module run trusted
local code and improve reliability; a deliberately malicious extension is out of scope (spec §7.3
— review an AI- or third-party-authored extension like any other local dependency). The
import-surface and determinism checks in particular are *reproducibility* rules (spec §3.2): an
effect that imports ``random`` or reads the wall clock produces output that a rerun cannot
reproduce, so validation flags it as an authoring error, not a threat.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic, has_errors
from arcavex.sdk.registration import COMPONENT_KINDS
from arcavex.services.extensions.loader import (
    _load_package,
    check_compatibility,
    instantiate_component,
)
from arcavex.services.extensions.manifest import (
    ComponentSpec,
    ExtensionManifest,
    parse_manifest,
)

# Component methods whose bodies are scanned for wall-clock / filesystem reads. The determinism
# rule (spec §3.2) targets the render-affecting code path — effect ``apply`` above all, plus the
# other contract entry points a component implements.
_COMPONENT_METHODS = frozenset({"apply", "build", "solve", "call", "export", "decode", "render"})

# Wall-clock reads that make output depend on when it ran (attribute call tails).
_WALL_CLOCK = frozenset(
    {"time", "monotonic", "perf_counter", "time_ns", "now", "today", "utcnow"}
)
# Filesystem-read call tails an effect must not perform on undeclared inputs.
_FS_READS = frozenset({"read_text", "read_bytes", "read"})


@dataclass
class ExtensionValidation:
    """The result of validating an extension directory: overall pass plus located diagnostics."""

    ok: bool
    name: str | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    components: list[str] = field(default_factory=list)


def validate_extension(ext_dir: Path) -> ExtensionValidation:
    """Run every validation gate over an extension directory and return the combined result.

    Manifest and compatibility problems short-circuit the dynamic checks (there is nothing sound
    to import); the import-surface and determinism scans are static and always run when the source
    files parse. Never raises.
    """
    ext_dir = Path(ext_dir)
    manifest, diagnostics = parse_manifest(ext_dir)
    if manifest is None:
        return ExtensionValidation(ok=False, diagnostics=diagnostics)

    compat = check_compatibility(manifest, ext_dir)
    if compat is not None:
        diagnostics.append(compat)

    diagnostics.extend(_scan_sources(ext_dir))

    if not any(c.code == "ARC-EXT-020" for c in diagnostics):
        # Dynamic checks import the entry modules; skip them only on an engine/IR mismatch, where
        # importing against the wrong build is not meaningful.
        diagnostics.extend(_validate_components(manifest, ext_dir))

    ok = not has_errors(diagnostics)
    return ExtensionValidation(
        ok=ok,
        name=manifest.name,
        diagnostics=diagnostics,
        components=[c.name for c in manifest.components],
    )


# --------------------------------------------------------------------------- static scans
def _scan_sources(ext_dir: Path) -> list[Diagnostic]:
    """Statically scan every ``.py`` file for disallowed imports and non-deterministic APIs."""
    diagnostics: list[Diagnostic] = []
    for py in sorted(ext_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except (OSError, SyntaxError) as exc:
            diagnostics.append(
                diagnostic(
                    "ARC-EXT-021",
                    f"Could not parse extension source {py.name}: {exc}",
                    file=str(py),
                    hint="Fix the Python syntax error.",
                )
            )
            continue
        diagnostics.extend(_scan_imports(tree, py))
        diagnostics.extend(_scan_determinism(tree, py))
    return diagnostics


def _scan_imports(tree: ast.Module, py: Path) -> list[Diagnostic]:
    """Flag any import that reaches an Arcavex module other than the public ``arcavex.sdk``."""
    diagnostics: list[Diagnostic] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_disallowed_arcavex(alias.name):
                    diagnostics.append(_import_diag(alias.name, py, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # A relative import (level > 0) stays inside the extension package — always allowed.
            if node.level == 0 and node.module is not None and _is_disallowed_arcavex(node.module):
                diagnostics.append(_import_diag(node.module, py, node.lineno))
    return diagnostics


def _is_disallowed_arcavex(module: str) -> bool:
    """Whether ``module`` is an Arcavex import outside the sanctioned ``arcavex.sdk`` surface."""
    if module != "arcavex" and not module.startswith("arcavex."):
        return False  # external or stdlib — not governed by the SDK-surface rule
    return module != "arcavex.sdk" and not module.startswith("arcavex.sdk.")


def _import_diag(module: str, py: Path, line: int) -> Diagnostic:
    return diagnostic(
        "ARC-EXT-030",
        f"Extension imports {module!r}, outside the arcavex.sdk surface",
        file=str(py),
        line=line,
        hint="Import only from 'arcavex.sdk' (it re-exports the contracts, helpers, and IR value "
        "types an extension may use). This keeps extensions insulated from engine internals; it "
        "is an authoring rule, not a security boundary.",
    )


def _scan_determinism(tree: ast.Module, py: Path) -> list[Diagnostic]:
    """Flag ``random`` imports (module-wide) and wall-clock / filesystem reads in component code.

    The determinism rule (spec §3.2) is about reproducibility: identical inputs must give
    identical output bytes, so an effect may not draw entropy from ``random`` or the clock, nor
    read an undeclared file. Randomness must come from the seeded ``ctx.rng``.
    """
    diagnostics: list[Diagnostic] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "random" or alias.name.startswith("random."):
                    diagnostics.append(_determinism_diag("imports 'random'", py, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module == "random":
            diagnostics.append(_determinism_diag("imports from 'random'", py, node.lineno))
    diagnostics.extend(_scan_component_bodies(tree, py))
    return diagnostics


def _scan_component_bodies(tree: ast.Module, py: Path) -> list[Diagnostic]:
    """Scan the bodies of contract methods (apply/build/…) for wall-clock and filesystem reads."""
    diagnostics: list[Diagnostic] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in _COMPONENT_METHODS:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            tail = _call_tail(call.func)
            if tail is None:
                continue
            if tail in _WALL_CLOCK:
                diagnostics.append(
                    _determinism_diag(
                        f"calls wall-clock '{tail}()' in {node.name}()", py, call.lineno
                    )
                )
            elif tail in _FS_READS or (isinstance(call.func, ast.Name) and call.func.id == "open"):
                what = "open()" if isinstance(call.func, ast.Name) else f"'{tail}()'"
                diagnostics.append(
                    _determinism_diag(
                        f"reads the filesystem via {what} in {node.name}()", py, call.lineno
                    )
                )
    return diagnostics


def _call_tail(func: ast.expr) -> str | None:
    """Return the final attribute/name of a call target (``time.monotonic`` -> ``monotonic``)."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _determinism_diag(what: str, py: Path, line: int) -> Diagnostic:
    return diagnostic(
        "ARC-EXT-031",
        f"Extension {what}, which breaks reproducible output",
        file=str(py),
        line=line,
        hint="Draw any randomness from the seeded 'ctx.rng' (arcavex.sdk.effect_rng), and do not "
        "read the wall clock or undeclared files — identical inputs must give identical bytes "
        "(spec §3.2).",
    )


# ------------------------------------------------------------------------- dynamic checks
def _validate_components(manifest: ExtensionManifest, ext_dir: Path) -> list[Diagnostic]:
    """Import each component and check its contract, name, param schema, and any shader."""
    diagnostics: list[Diagnostic] = []
    package = _load_package(manifest.name, ext_dir)
    for spec in manifest.components:
        diagnostics.extend(_validate_component(package, ext_dir, spec))
    return diagnostics


def _validate_component(package: str, ext_dir: Path, spec: ComponentSpec) -> list[Diagnostic]:
    kind = COMPONENT_KINDS[spec.kind]
    module_name = f"{package}.{spec.module}"
    try:
        import importlib

        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - import failure is one located diagnostic
        return [
            diagnostic(
                "ARC-EXT-021",
                f"Could not import entry module {spec.module!r} of component {spec.name!r}: {exc}",
                file=str(ext_dir),
                hint="Check the module imports only arcavex.sdk and has no import-time errors.",
            )
        ]
    cls = getattr(module, spec.class_name, None)
    if cls is None or not isinstance(cls, type):
        return [
            diagnostic(
                "ARC-EXT-021",
                f"Entry class {spec.class_name!r} not found in module {spec.module!r}",
                file=str(ext_dir),
                hint=f"Define class {spec.class_name} in {spec.module}.py.",
            )
        ]
    diagnostics: list[Diagnostic] = []
    if not issubclass(cls, kind.contract):
        diagnostics.append(
            diagnostic(
                "ARC-EXT-022",
                f"Component {spec.name!r} ({spec.class_name}) does not implement the "
                f"{kind.contract.__name__} contract",
                file=str(ext_dir),
                hint=f"Subclass arcavex.sdk.{kind.contract.__name__} and implement its methods.",
            )
        )
        return diagnostics
    diagnostics.extend(_check_name_attr(cls, kind, spec, ext_dir))
    diagnostics.extend(_check_param_schema(cls, spec, ext_dir))
    diagnostics.extend(_check_shader(cls, spec, ext_dir))
    # Instantiate last: it surfaces an unimplemented abstract method as a located diagnostic
    # rather than an import-time crash when the extension is enabled.
    try:
        instantiate_component(package, ext_dir, spec)
    except DiagnosticError as exc:
        diagnostics.extend(exc.diagnostics)
    return diagnostics


def _check_name_attr(
    cls: type, kind: object, spec: ComponentSpec, ext_dir: Path
) -> list[Diagnostic]:
    name_attr = kind.name_attr  # type: ignore[attr-defined]
    if name_attr is None:
        return []
    declared = getattr(cls, name_attr, None)
    if declared != spec.name:
        return [
            diagnostic(
                "ARC-EXT-022",
                f"Component {spec.name!r} declares {name_attr}={declared!r}, which does not match "
                "its manifest name",
                file=str(ext_dir),
                hint=f"Set '{name_attr}' on {spec.class_name} to {spec.name!r} so the class and "
                "manifest agree.",
            )
        ]
    return []


def _check_param_schema(cls: type, spec: ComponentSpec, ext_dir: Path) -> list[Diagnostic]:
    """Effects, masks, and shapes must expose a pydantic ``param_schema`` (spec §3.2)."""
    if spec.kind not in {"effect", "mask", "shape"}:
        return []
    schema = getattr(cls, "param_schema", None)
    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        return [
            diagnostic(
                "ARC-EXT-023",
                f"Component {spec.name!r} has no valid pydantic 'param_schema'",
                file=str(ext_dir),
                hint="Set 'param_schema' to a pydantic BaseModel subclass describing the "
                "component's parameters.",
            )
        ]
    try:
        _ = schema.model_fields
    except Exception as exc:  # noqa: BLE001 - a broken schema is one located diagnostic
        return [
            diagnostic(
                "ARC-EXT-023",
                f"Component {spec.name!r} param_schema is not a usable pydantic model: {exc}",
                file=str(ext_dir),
                hint="Ensure the schema is a valid pydantic v2 BaseModel.",
            )
        ]
    return []


def _check_shader(cls: type, spec: ComponentSpec, ext_dir: Path) -> list[Diagnostic]:
    """Compile an SkSL shader the component declares (class attribute ``SKSL``), if any.

    A component that renders through SkSL may expose its shader source as a ``SKSL`` class
    attribute; the validator compiles it up front so a shader typo is a located ``ARC-EXT-032``
    at validate time instead of a render-time crash (spec §7.2).
    """
    source = getattr(cls, "SKSL", None)
    if not isinstance(source, str):
        return []
    import skia  # type: ignore[import-untyped]

    try:
        effect = skia.RuntimeEffect.MakeForShader(source)
    except Exception as exc:  # noqa: BLE001 - a compile failure is one located diagnostic
        return [
            diagnostic(
                "ARC-EXT-032",
                f"Component {spec.name!r} SkSL shader failed to compile: {exc}",
                file=str(ext_dir),
                hint="Fix the SkSL source; the error message reports the offending line.",
            )
        ]
    if effect is None:
        return [
            diagnostic(
                "ARC-EXT-032",
                f"Component {spec.name!r} SkSL shader failed to compile",
                file=str(ext_dir),
                hint="Fix the SkSL source so RuntimeEffect.MakeForShader accepts it.",
            )
        ]
    return []


__all__ = ["ExtensionValidation", "validate_extension"]

"""The service API facade — the one front door above the kernel.

Clients (CLI, MCP, Python) call this facade and never reach into services or built-ins
directly. The facade orchestrates the pipeline (compile -> layout -> render -> export)
using dependencies injected by :mod:`arcavex.bootstrap`, so the kernel imports nothing from
services or built-ins. No raw exception ever leaves this module: unexpected errors are
wrapped as ``ARC-INT-999`` diagnostics.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from arcavex.kernel.contracts.types import (
    ExportOptions,
    MeasureFn,
    RenderOptions,
)
from arcavex.kernel.diagnostics import (
    Diagnostic,
    DiagnosticError,
    diagnostic,
    has_errors,
    internal_error,
)
from arcavex.kernel.ir.models import (
    CompiledDocument,
    CompiledGroup,
    CompiledImage,
    CompiledNode,
)
from arcavex.kernel.registry import Registries

_EXPORTER_BY_EXT: dict[str, str] = {
    ".png": "png",
}

# Machine-readable responses carry this so consumers key on a version, not a shape.
RESPONSE_VERSION = 1


def _dedupe(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Remove duplicate diagnostics while preserving first-seen order."""
    seen: set[tuple[object, ...]] = set()
    out: list[Diagnostic] = []
    for diag in diagnostics:
        src = diag.source
        key = (
            diag.code,
            diag.message,
            None if src is None else (src.file, src.keypath, src.line),
        )
        if key not in seen:
            seen.add(key)
            out.append(diag)
    return out


@dataclass
class CompileResult:
    """The output of compilation: a document (on success) and diagnostics.

    ``inferred`` records unambiguous choices the compiler made on the caller's behalf
    (e.g. ``{"format": "square", "data": "preview_data"}``) so clients can report them
    (§6.3). ``format_name`` is the format actually compiled, used for default output naming.
    """

    document: CompiledDocument | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    inferred: dict[str, str] = field(default_factory=dict)
    format_name: str | None = None


class CompilerProtocol(Protocol):
    """The compiler dependency injected by bootstrap."""

    def compile(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
    ) -> CompileResult:
        """Compile a template + data into a :class:`CompiledDocument`."""
        ...

    def list_formats(self, template: Path) -> list[str]:
        """Return the names of formats declared by a template (best effort)."""
        ...

    def resolve_paths(self, template: Path) -> tuple[Path, Path]:
        """Return ``(root_dir, template_yaml)`` for a template path (file or directory)."""
        ...


class RenderResult(BaseModel):
    """The result of a render request."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    output_path: str | None
    diagnostics: list[Diagnostic]
    content_sha256: str | None = None
    inferred: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- doctor
class DoctorCheck(BaseModel):
    """One environment probe result in a doctor report."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: Literal["ok", "warn", "fail"]
    detail: str
    hint: str | None = None


class DoctorReport(BaseModel):
    """The result of ``arcavex doctor``: engine version plus per-probe check rows."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    engine_version: str
    checks: list[DoctorCheck]


# --------------------------------------------------------------------------- explain
class DiagnosticHelp(BaseModel):
    """The result of ``arcavex explain``: a documentation entry for a diagnostic code."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    code: str
    found: bool
    title: str | None = None
    summary: str | None = None
    fix: str | None = None
    message: str | None = None  # populated when the code is unknown


# ------------------------------------------------------------------ template authoring
class VariableInfo(BaseModel):
    """A declared template variable, as reported by inspect.

    ``has_default`` distinguishes a variable with no declared default from one declared as
    ``default: null`` (both serialize ``default`` as ``null``), so a machine consumer can
    recover the authored contract exactly (CR-11).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    type: str | None = None
    required: bool = False
    has_default: bool = False
    default: Any = None
    doc: str | None = None
    enum: list[Any] | None = None


class FormatInfo(BaseModel):
    """A declared format's canvas, as reported by inspect.

    ``width``/``height`` echo the authored strings (e.g. ``"1080px"``) so an AI author can
    round-trip a size without converting from the internal points, which ``width_pt`` reports
    for layout math (DX-7).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    width: str | None = None
    height: str | None = None
    width_pt: float
    height_pt: float
    dpi: int


class NodeInfo(BaseModel):
    """An authored node in the template contract, as reported by inspect.

    Nodes are reported as authored, not expanded (DX-3): a ``repeat``/``if`` construct appears
    once with its ``origin`` and the condition/collection expression, so a consumer sees the
    full structural contract regardless of what the preview data happens to instantiate.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    type: str
    origin: Literal["static", "repeat", "if"] = "static"
    condition: str | None = None  # the 'if' expression, for origin == "if"
    collection: str | None = None  # the 'repeat' expression, for origin == "repeat"
    loop_var: str | None = None  # the repeat 'as' name
    key: str | None = None  # the repeat 'key' expression


class FunctionInfo(BaseModel):
    """A registered template function's name, signature, and one-line doc (DX-3)."""

    model_config = ConfigDict(frozen=True)

    name: str
    signature: str
    doc: str | None = None


class TemplateInspectReport(BaseModel):
    """The result of ``arcavex template inspect``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    compiled: bool = False
    version: str | None = None
    is_split: bool = False
    variables: list[VariableInfo] = Field(default_factory=list)
    formats: list[FormatInfo] = Field(default_factory=list)
    nodes: list[NodeInfo] = Field(default_factory=list)
    functions: list[FunctionInfo] = Field(default_factory=list)
    preview_data: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ScaffoldResult(BaseModel):
    """The result of ``arcavex template new``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    path: str | None = None
    format: str | None = None
    files: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class CheckResult(BaseModel):
    """The result of ``arcavex template check``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class SplitResult(BaseModel):
    """The result of ``arcavex template split``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    directory: str | None = None
    files: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class PreviewResult(BaseModel):
    """The result of a single ``arcavex preview`` render (watch or one-shot)."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    output_path: str | None = None
    changed_file: str | None = None
    compile_ms: float | None = None
    render_ms: float | None = None
    content_sha256: str | None = None
    inferred: dict[str, str] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class AuthoringProtocol(Protocol):
    """Template authoring operations injected by bootstrap (scaffold/inspect/split)."""

    def scaffold(self, name: str, target: Path) -> ScaffoldResult:
        """Scaffold a new renderable template directory at ``target``."""
        ...

    def inspect(self, template: Path) -> TemplateInspectReport:
        """Inspect a template's variables, formats, nodes, and functions."""
        ...

    def split(self, template: Path) -> SplitResult:
        """Convert a one-file template into a split directory losslessly."""
        ...


class Facade:
    """Orchestrates the pipeline using injected, kernel-external dependencies."""

    def __init__(
        self,
        registries: Registries,
        compiler: CompilerProtocol,
        measure_fn: MeasureFn,
        *,
        default_layout: str = "anchors",
        default_backend: str = "skia",
        doctor_probe: Callable[[], DoctorReport] | None = None,
        explain_lookup: Callable[[str], DiagnosticHelp] | None = None,
        authoring: AuthoringProtocol | None = None,
        preview_root: Path | None = None,
    ) -> None:
        """Wire the facade.

        Args:
            registries: The populated component registries.
            compiler: The template compiler.
            measure_fn: The text measurement function used by layout.
            default_layout: Name of the default layout solver.
            default_backend: Name of the default renderer backend.
            doctor_probe: Callable returning the environment doctor report.
            explain_lookup: Callable resolving a diagnostic code to help.
            authoring: The template authoring service (scaffold/inspect/split).
            preview_root: Directory for stable preview outputs (defaults to an OS temp dir).
        """
        self._registries = registries
        self._compiler = compiler
        self._measure = measure_fn
        self._default_layout = default_layout
        self._default_backend = default_backend
        self._doctor_probe = doctor_probe
        self._explain_lookup = explain_lookup
        self._authoring = authoring
        self._preview_root = preview_root

    def validate_template(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> list[Diagnostic]:
        """Compile through semantic validation and return accumulated diagnostics.

        Never raises: unexpected failures are returned as an ``ARC-INT-999`` diagnostic.
        """
        try:
            targets: list[str | None]
            if format_name is None:
                formats = self._compiler.list_formats(template)
                # Validate against every declared format when the choice is ambiguous, so
                # a caller need not pick one just to check the template structurally.
                targets = list(formats) if len(formats) > 1 else [None]
            else:
                targets = [format_name]

            aggregated: list[Diagnostic] = []
            for target in targets:
                aggregated.extend(
                    self._validate_one(template, data, target, locale, style)
                )
            return _dedupe(aggregated)
        except DiagnosticError as exc:
            return list(exc.diagnostics)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return [internal_error("Validation failed unexpectedly", detail=repr(exc))]

    def _validate_one(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
    ) -> list[Diagnostic]:
        result = self._compiler.compile(template, data, format_name, locale, style)
        diagnostics = list(result.diagnostics)
        if result.document is not None and not has_errors(diagnostics):
            # Exercise layout so under/over-constrained nodes surface during validate.
            diagnostics.extend(self._try_layout(result.document))
        return diagnostics

    def render_file(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
        output: Path | None = None,
        dpi: int | None = None,
        debug: bool = False,
    ) -> RenderResult:
        """Compile, lay out, render, and export a template to ``output``.

        Never raises: unexpected failures are returned in the result's diagnostics.

        The default output name (§6.3) is resolved up front from the template stem and the
        resolved format and carried in ``inferred`` on *every* return path — success, a
        ``DiagnosticError``, or an unexpected failure — so the user always learns what would
        have been written, even when the render fails (CR-1).
        """
        inferred_base: dict[str, str] = {}
        resolved_output = output
        if output is None:
            default_output = self._default_output_path(template, format_name)
            if default_output is not None:
                resolved_output = default_output
                inferred_base["output"] = str(default_output)
        try:
            return self._render_file_inner(
                template, data, format_name, locale, style, resolved_output, dpi, debug,
                inferred_base,
            )
        except DiagnosticError as exc:
            return RenderResult(
                ok=False,
                output_path=None,
                diagnostics=list(exc.diagnostics),
                inferred=dict(inferred_base),
            )
        except Exception:  # noqa: BLE001 - facade boundary must not leak
            last_line = traceback.format_exc().splitlines()[-1]
            return RenderResult(
                ok=False,
                output_path=None,
                diagnostics=[internal_error("Render failed unexpectedly", detail=last_line)],
                inferred=dict(inferred_base),
            )

    # ------------------------------------------------------------------ internals
    def _default_stem(self, template: Path) -> str:
        """Return the default output stem for a template path (directory name or file stem).

        A directory template, or its ``template.yaml`` file, both yield the directory name, so
        the two spellings produce identical default names (CR-4). A one-file template named
        something other than ``template.yaml`` yields that file's stem.
        """
        try:
            root_dir, template_yaml = self._compiler.resolve_paths(template)
        except Exception:  # noqa: BLE001 - fall back to the raw path when resolution fails
            return Path(template).stem
        if template_yaml.name == "template.yaml":
            return root_dir.name
        return template_yaml.stem

    def _default_output_path(self, template: Path, format_name: str | None) -> Path | None:
        """Resolve the deterministic default output path, or ``None`` if the format is ambiguous.

        The format follows the same sole-format inference the compiler uses, so the name is
        available before rendering; when several formats exist and none was chosen the name is
        genuinely unknown (ambiguity is a diagnostic, not a silent pick).
        """
        fmt = format_name
        if fmt is None:
            formats = self._compiler.list_formats(template)
            if len(formats) != 1:
                return None
            fmt = formats[0]
        return Path(f"{self._default_stem(template)}.{fmt}.png")

    def _render_file_inner(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        output: Path | None,
        dpi: int | None,
        debug: bool,
        inferred_base: dict[str, str],
    ) -> RenderResult:
        compiled = self._compiler.compile(template, data, format_name, locale, style)
        diagnostics = list(compiled.diagnostics)
        inferred = {**inferred_base, **dict(compiled.inferred)}
        if compiled.document is None or has_errors(diagnostics):
            return RenderResult(
                ok=False, output_path=None, diagnostics=diagnostics, inferred=inferred
            )

        if output is None:
            # Safety net for the ambiguous-format path (compile normally raises ARC-TPL-021
            # before here): name from the format the compiler actually resolved.
            fmt = compiled.format_name or "out"
            output = Path(f"{self._default_stem(template)}.{fmt}.png")
            inferred["output"] = str(output)

        exporter_name = _EXPORTER_BY_EXT.get(output.suffix.lower())
        if exporter_name is None:
            return RenderResult(
                ok=False,
                output_path=None,
                inferred=inferred,
                diagnostics=[
                    diagnostic(
                        "ARC-EXP-011",
                        f"Unsupported output extension {output.suffix!r}",
                        hint="Phase 0 exports PNG only. Use a '.png' output path.",
                    )
                ],
            )

        solver = self._registries.layouts.get(self._default_layout)
        layout = solver.solve(compiled.document, self._measure)

        backend = self._registries.backends.get(self._default_backend)
        surface = backend.render(layout, RenderOptions(dpi=dpi, debug=debug))

        exporter = self._registries.exporters.get(exporter_name)
        output.parent.mkdir(parents=True, exist_ok=True)
        report = exporter.export(surface, output, ExportOptions(dpi=dpi))

        return RenderResult(
            ok=True,
            output_path=report.path,
            diagnostics=diagnostics,
            content_sha256=report.content_sha256,
            inferred=inferred,
        )

    def _try_layout(self, document: CompiledDocument) -> list[Diagnostic]:
        try:
            solver = self._registries.layouts.get(self._default_layout)
            solver.solve(document, self._measure)
            return []
        except DiagnosticError as exc:
            return list(exc.diagnostics)

    # ------------------------------------------------------------------ authoring
    def doctor(self) -> DoctorReport:
        """Run environment probes and return a report. Never raises."""
        if self._doctor_probe is None:  # pragma: no cover - always wired in production
            return DoctorReport(
                ok=False,
                engine_version="unknown",
                checks=[
                    DoctorCheck(
                        name="doctor",
                        status="fail",
                        detail="doctor probe is not wired",
                        hint="This is a build configuration error.",
                    )
                ],
            )
        try:
            return self._doctor_probe()
        except Exception as exc:  # noqa: BLE001 - doctor must never crash
            return DoctorReport(
                ok=False,
                engine_version="unknown",
                checks=[
                    DoctorCheck(
                        name="doctor",
                        status="fail",
                        detail=f"doctor failed unexpectedly: {exc!r}",
                        hint="Please report this with your environment details.",
                    )
                ],
            )

    def explain_diagnostic(self, code: str) -> DiagnosticHelp:
        """Return documentation for a diagnostic code. Never raises."""
        normalized = code.strip().upper()
        if self._explain_lookup is None:  # pragma: no cover - always wired in production
            return DiagnosticHelp(
                code=normalized, found=False, message="explain is not wired"
            )
        try:
            return self._explain_lookup(normalized)
        except Exception as exc:  # noqa: BLE001 - explain must never crash
            return DiagnosticHelp(
                code=normalized, found=False, message=f"explain failed: {exc!r}"
            )

    def scaffold_template(self, name: str, target: Path) -> ScaffoldResult:
        """Scaffold a new renderable one-file template directory. Never raises."""
        if self._authoring is None:  # pragma: no cover - always wired in production
            return ScaffoldResult(ok=False, diagnostics=[_unwired("authoring")])
        try:
            return self._authoring.scaffold(name, Path(target))
        except DiagnosticError as exc:
            return ScaffoldResult(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ScaffoldResult(
                ok=False, diagnostics=[internal_error("Scaffold failed", detail=repr(exc))]
            )

    def check_template(
        self, template: Path, format_name: str | None = None, locale: str | None = None
    ) -> CheckResult:
        """Validate a template without data (schema + structure + preview_data)."""
        diagnostics = self.validate_template(
            template, data=None, format_name=format_name, locale=locale
        )
        return CheckResult(ok=not has_errors(diagnostics), diagnostics=diagnostics)

    def inspect_template(self, template: Path) -> TemplateInspectReport:
        """Inspect a template's contract. Never raises."""
        if self._authoring is None:  # pragma: no cover - always wired in production
            return TemplateInspectReport(ok=False, diagnostics=[_unwired("authoring")])
        try:
            return self._authoring.inspect(Path(template))
        except DiagnosticError as exc:
            return TemplateInspectReport(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return TemplateInspectReport(
                ok=False, diagnostics=[internal_error("Inspect failed", detail=repr(exc))]
            )

    def split_template(self, template: Path) -> SplitResult:
        """Convert a one-file template into a split directory losslessly. Never raises."""
        if self._authoring is None:  # pragma: no cover - always wired in production
            return SplitResult(ok=False, diagnostics=[_unwired("authoring")])
        try:
            return self._authoring.split(Path(template))
        except DiagnosticError as exc:
            return SplitResult(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return SplitResult(
                ok=False, diagnostics=[internal_error("Split failed", detail=repr(exc))]
            )

    # -------------------------------------------------------------------- preview
    def preview_path(self, template: Path, format_name: str) -> Path:
        """Return the stable preview output path for a template + format.

        The path is derived from the resolved ``template.yaml`` so the same template always
        previews to the same file regardless of whether the caller passed the directory or the
        file (§4.1.1 path equivalence, CR-4), under ``$ARCAVEX_HOME/cache/preview`` or an OS
        temp directory.
        """
        try:
            _root_dir, template_yaml = self._compiler.resolve_paths(template)
            base = template_yaml
        except Exception:  # noqa: BLE001 - fall back to the raw path when resolution fails
            base = Path(template)
        key = hashlib.sha256(str(base.resolve()).encode("utf-8")).hexdigest()[:16]
        root = self._resolve_preview_root()
        return root / f"{key}.{format_name}.png"

    def render_preview(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
        dpi: int | None = None,
        changed_file: str | None = None,
    ) -> PreviewResult:
        """Render to the stable preview path atomically, with compile/render timings.

        Never raises and never creates a recorded run. On failure the previous preview file is
        left untouched (the atomic temp+replace only runs on success), so a viewer keeps the
        last good image (spec §6.3).
        """
        try:
            return self._render_preview_inner(
                template, data, format_name, locale, style, dpi, changed_file
            )
        except DiagnosticError as exc:
            return PreviewResult(
                ok=False, changed_file=changed_file, diagnostics=list(exc.diagnostics)
            )
        except Exception:  # noqa: BLE001 - facade boundary must not leak
            last_line = traceback.format_exc().splitlines()[-1]
            return PreviewResult(
                ok=False,
                changed_file=changed_file,
                diagnostics=[internal_error("Preview failed unexpectedly", detail=last_line)],
            )

    def _render_preview_inner(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        dpi: int | None,
        changed_file: str | None,
    ) -> PreviewResult:
        compile_start = time.perf_counter()
        compiled = self._compiler.compile(template, data, format_name, locale, style)
        compile_ms = (time.perf_counter() - compile_start) * 1000.0
        diagnostics = list(compiled.diagnostics)
        inferred = dict(compiled.inferred)
        if compiled.document is None or has_errors(diagnostics):
            return PreviewResult(
                ok=False,
                changed_file=changed_file,
                compile_ms=compile_ms,
                inferred=inferred,
                diagnostics=diagnostics,
            )

        resolved_format = compiled.format_name or "out"
        out_path = self.preview_path(template, resolved_format)

        render_start = time.perf_counter()
        solver = self._registries.layouts.get(self._default_layout)
        layout = solver.solve(compiled.document, self._measure)
        backend = self._registries.backends.get(self._default_backend)
        surface = backend.render(layout, RenderOptions(dpi=dpi, debug=False))
        exporter = self._registries.exporters.get("png")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: export to a unique temp file in the same directory, then os.replace so
        # a watcher never observes a torn PNG and a failed render leaves the old file intact.
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(out_path.parent), prefix=".preview-", suffix=".png"
        )
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)
        try:
            report = exporter.export(surface, tmp_path, ExportOptions(dpi=dpi))
            os.replace(tmp_path, out_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        render_ms = (time.perf_counter() - render_start) * 1000.0

        return PreviewResult(
            ok=True,
            output_path=str(out_path),
            changed_file=changed_file,
            compile_ms=compile_ms,
            render_ms=render_ms,
            content_sha256=report.content_sha256,
            inferred=inferred,
            diagnostics=diagnostics,
        )

    def collect_asset_paths(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> list[str]:
        """Return the resolved image-asset paths a template references (best effort, CR-9).

        Used by watch mode to also observe out-of-tree assets. Never raises: on any compile
        failure it returns an empty list, so watching degrades gracefully.
        """
        try:
            compiled = self._compiler.compile(template, data, format_name, locale, style)
        except Exception:  # noqa: BLE001 - best-effort asset discovery must not crash watch
            return []
        if compiled.document is None:
            return []
        out: list[str] = []

        def visit(node: CompiledNode) -> None:
            if isinstance(node, CompiledImage):
                out.append(node.asset_path)
            if isinstance(node, CompiledGroup):
                for child in node.children:
                    visit(child)

        visit(compiled.document.root)
        return out

    def _resolve_preview_root(self) -> Path:
        if self._preview_root is not None:
            return self._preview_root
        home = os.environ.get("ARCAVEX_HOME")
        if home:
            return Path(home) / "cache" / "preview"
        return Path(tempfile.gettempdir()) / "arcavex" / "cache" / "preview"


def _unwired(what: str) -> Diagnostic:
    return internal_error(f"{what} service is not wired")

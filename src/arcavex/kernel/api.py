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
from arcavex.kernel.ir.models import CompiledDocument
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
    """A declared template variable, as reported by inspect."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str | None = None
    required: bool = False
    default: Any = None
    doc: str | None = None
    enum: list[Any] | None = None


class FormatInfo(BaseModel):
    """A declared format's resolved canvas, as reported by inspect."""

    model_config = ConfigDict(frozen=True)

    name: str
    width_pt: float
    height_pt: float
    dpi: int


class NodeInfo(BaseModel):
    """A compiled node's id and kind, as reported by inspect."""

    model_config = ConfigDict(frozen=True)

    id: str
    type: str


class TemplateInspectReport(BaseModel):
    """The result of ``arcavex template inspect``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    version: str | None = None
    is_split: bool = False
    variables: list[VariableInfo] = Field(default_factory=list)
    formats: list[FormatInfo] = Field(default_factory=list)
    nodes: list[NodeInfo] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
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
        """
        try:
            return self._render_file_inner(
                template, data, format_name, locale, style, output, dpi, debug
            )
        except DiagnosticError as exc:
            return RenderResult(
                ok=False, output_path=None, diagnostics=list(exc.diagnostics)
            )
        except Exception:  # noqa: BLE001 - facade boundary must not leak
            last_line = traceback.format_exc().splitlines()[-1]
            return RenderResult(
                ok=False,
                output_path=None,
                diagnostics=[internal_error("Render failed unexpectedly", detail=last_line)],
            )

    # ------------------------------------------------------------------ internals
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
    ) -> RenderResult:
        compiled = self._compiler.compile(template, data, format_name, locale, style)
        diagnostics = list(compiled.diagnostics)
        inferred = dict(compiled.inferred)
        if compiled.document is None or has_errors(diagnostics):
            return RenderResult(
                ok=False, output_path=None, diagnostics=diagnostics, inferred=inferred
            )

        if output is None:
            # §6.3: a deterministic default output name, reported to the caller. The
            # resolved format (possibly itself inferred) drives the stem.
            fmt = compiled.format_name or "out"
            output = Path(f"{Path(template).stem}.{fmt}.png")
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
        self, template: Path, format_name: str | None = None
    ) -> CheckResult:
        """Validate a template without data (schema + structure + preview_data)."""
        diagnostics = self.validate_template(template, data=None, format_name=format_name)
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

        The path is derived from the absolute template path so the same template always
        previews to the same file (spec §6.1.1), under ``$ARCAVEX_HOME/cache/preview`` or an
        OS temp directory.
        """
        key = hashlib.sha256(str(Path(template).resolve()).encode("utf-8")).hexdigest()[:16]
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

    def _resolve_preview_root(self) -> Path:
        if self._preview_root is not None:
            return self._preview_root
        home = os.environ.get("ARCAVEX_HOME")
        if home:
            return Path(home) / "cache" / "preview"
        return Path(tempfile.gettempdir()) / "arcavex" / "cache" / "preview"


def _unwired(what: str) -> Diagnostic:
    return internal_error(f"{what} service is not wired")

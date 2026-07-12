"""The service API facade — the one front door above the kernel.

Clients (CLI, MCP, Python) call this facade and never reach into services or built-ins
directly. The facade orchestrates the pipeline (compile -> layout -> render -> export)
using dependencies injected by :mod:`arcavex.bootstrap`, so the kernel imports nothing from
services or built-ins. No raw exception ever leaves this module: unexpected errors are
wrapped as ``ARC-INT-999`` diagnostics.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

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
    ) -> None:
        """Wire the facade.

        Args:
            registries: The populated component registries.
            compiler: The template compiler.
            measure_fn: The text measurement function used by layout.
            default_layout: Name of the default layout solver.
            default_backend: Name of the default renderer backend.
        """
        self._registries = registries
        self._compiler = compiler
        self._measure = measure_fn
        self._default_layout = default_layout
        self._default_backend = default_backend

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

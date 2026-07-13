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
    LayoutDocument,
    LayoutNode,
)
from arcavex.kernel.registry import Registries

_EXPORTER_BY_EXT: dict[str, str] = {
    ".png": "png",
}

# Machine-readable responses carry this so consumers key on a version, not a shape.
RESPONSE_VERSION = 1


def _output_name(stem: str, fmt: str, locale: str | None) -> str:
    """Build the default output filename ``<stem>.<format>[.<locale>].png`` (§6.3 / DX-3)."""
    locale_seg = f".{locale}" if locale else ""
    return f"{stem}.{fmt}{locale_seg}.png"


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


@dataclass
class ResolvedPatch:
    """One applied patch operation plus the value it produced (for --resolved)."""

    layer: str
    op: str
    path: str
    value: Any = None
    effective: bool = True


@dataclass
class ResolvedResult:
    """The compiler's provenance view for ``template inspect --resolved`` (CR-1)."""

    ok: bool
    format_name: str | None = None
    locale: str | None = None
    direction: str | None = None
    digits: str | None = None
    patches: list[ResolvedPatch] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


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

    def inspect_resolved(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
    ) -> ResolvedResult:
        """Report the final layered values and their originating layers (--resolved)."""
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


class ResolvedPatchInfo(BaseModel):
    """One applied patch op and the value it produced, for --resolved output."""

    model_config = ConfigDict(frozen=True)

    layer: str
    op: str
    path: str
    value: Any = None
    effective: bool = True


class TemplateResolvedReport(BaseModel):
    """The result of ``arcavex template inspect --resolved`` (CR-1).

    Reports the resolved format/locale settings and the ordered list of applied format/locale
    patches with the final value each produced and its originating layer. The last op on a
    given path is marked ``effective`` — that is where the final value came from.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    format: str | None = None
    locale: str | None = None
    direction: str | None = None
    digits: str | None = None
    patches: list[ResolvedPatchInfo] = Field(default_factory=list)
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


# --------------------------------------------------------------------- layout inspection
class AnchorDerivation(BaseModel):
    """How one axis position of a node was derived from its anchor."""

    model_config = ConfigDict(frozen=True)

    axis: Literal["horizontal", "vertical"]
    edge: str  # the pinned edge of this node (physical, after logical resolution)
    expression: str  # e.g. "title.bottom + 16pt"
    resolved_pt: float


class OverflowReport(BaseModel):
    """A node's text-overflow outcome, echoed for inspection."""

    model_config = ConfigDict(frozen=True)

    kind: str
    measured_w_pt: float
    measured_h_pt: float
    box_w_pt: float
    box_h_pt: float


class LayoutNodeReport(BaseModel):
    """Resolved geometry and derivation for one node."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    bounds_pt: tuple[float, float, float, float]
    bounds_px: tuple[float, float, float, float]
    paint_bounds_pt: tuple[float, float, float, float]
    paint_bounds_px: tuple[float, float, float, float]
    # The node's absolute affine transform as (a, b, c, d, e, f); identity for unrotated nodes.
    absolute_transform: tuple[float, float, float, float, float, float]
    rotate_deg: float = 0.0
    overflow: OverflowReport | None = None
    anchors: list[AnchorDerivation] = Field(default_factory=list)
    children: list[LayoutNodeReport] = Field(default_factory=list)


class SiblingOverlap(BaseModel):
    """Two sibling nodes whose resolved bounds intersect."""

    model_config = ConfigDict(frozen=True)

    a: str
    b: str
    rect_pt: tuple[float, float, float, float]


class LayoutReport(BaseModel):
    """The result of ``arcavex layout inspect`` (versioned JSON)."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    format: str | None = None
    locale: str | None = None
    canvas_pt: tuple[float, float] = (0.0, 0.0)
    canvas_px: tuple[int, int] = (0, 0)
    dpi: int = 0
    root: LayoutNodeReport | None = None
    overlaps: list[SiblingOverlap] = Field(default_factory=list)
    covered_fraction: float = 0.0
    # Maximal full-width empty horizontal bands (uncovered canvas), largest first — the summary
    # that surfaces e.g. an unfilled bottom slab (spec §6.1.1 free regions).
    free_regions: list[tuple[float, float, float, float]] = Field(default_factory=list)
    inferred: dict[str, str] = Field(default_factory=dict)
    warnings: list[Diagnostic] = Field(default_factory=list)
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
            default_output = self._default_output_path(template, format_name, locale)
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

    def render_plan(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        output: Path | None = None,
        locale: str | None = None,
    ) -> dict[str, str]:
        """Resolve the render-affecting inferences (output name, sole format) up front (RR1-3).

        These are cheap to compute without compiling, so a client can announce them before a
        long render begins rather than only after it finishes. Never raises.
        """
        inferred: dict[str, str] = {}
        try:
            if output is None:
                default = self._default_output_path(template, format_name, locale)
                if default is not None:
                    inferred["output"] = str(default)
            if format_name is None:
                formats = self._compiler.list_formats(template)
                if len(formats) == 1:
                    inferred["format"] = formats[0]
        except Exception:  # noqa: BLE001 - a best-effort plan must never fail the render
            return inferred
        return inferred

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

    def _default_output_path(
        self, template: Path, format_name: str | None, locale: str | None = None
    ) -> Path | None:
        """Resolve the deterministic default output path, or ``None`` if the format is ambiguous.

        The name follows §6.3: ``<stem>.<format>[.<locale>].png``. The format follows the same
        sole-format inference the compiler uses, so the name is available before rendering; when
        several formats exist and none was chosen the name is genuinely unknown (ambiguity is a
        diagnostic, not a silent pick). The locale segment is present only when a locale is
        applied, so ``--locale fa`` never overwrites the ``en`` render (DX-3).
        """
        fmt = format_name
        if fmt is None:
            formats = self._compiler.list_formats(template)
            if len(formats) != 1:
                return None
            fmt = formats[0]
        return Path(_output_name(self._default_stem(template), fmt, locale))

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
            output = Path(_output_name(self._default_stem(template), fmt, locale))
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
        diagnostics.extend(layout.warnings)

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
            layout = solver.solve(document, self._measure)
            # Layout raises warnings (missing glyphs, fit non-convergence) that validate
            # should surface alongside compile diagnostics.
            return list(layout.warnings)
        except DiagnosticError as exc:
            return list(exc.diagnostics)

    # ------------------------------------------------------------------ layout inspect
    def inspect_layout(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> LayoutReport:
        """Compile and lay out a template and report resolved geometry. Never raises.

        Reports per-node resolved bounds (points and device pixels), paint bounds, rotation,
        text-overflow state, the anchor derivation for each axis, sibling overlaps, and a
        coverage summary (spec §6.1.1).
        """
        try:
            return self._inspect_layout_inner(template, data, format_name, locale, style)
        except DiagnosticError as exc:
            return LayoutReport(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return LayoutReport(
                ok=False, diagnostics=[internal_error("Layout inspect failed", detail=repr(exc))]
            )

    def _inspect_layout_inner(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
    ) -> LayoutReport:
        compiled = self._compiler.compile(template, data, format_name, locale, style)
        diagnostics = list(compiled.diagnostics)
        inferred = dict(compiled.inferred)
        if compiled.document is None or has_errors(diagnostics):
            return LayoutReport(
                ok=False, format=format_name, locale=locale, inferred=inferred,
                diagnostics=diagnostics,
            )
        solver = self._registries.layouts.get(self._default_layout)
        layout = solver.solve(compiled.document, self._measure)
        dpi = compiled.document.canvas.dpi
        overlaps: list[SiblingOverlap] = []
        root = _build_node_report(
            compiled.document.root, layout.root, compiled.document.root.direction, dpi, overlaps
        )
        covered = _covered_fraction(layout)
        return LayoutReport(
            ok=True,
            format=compiled.format_name or format_name,
            locale=locale,
            canvas_pt=(compiled.document.canvas.width_pt, compiled.document.canvas.height_pt),
            canvas_px=(compiled.document.canvas.width_px, compiled.document.canvas.height_px),
            dpi=dpi,
            root=root,
            overlaps=overlaps,
            covered_fraction=covered,
            free_regions=_free_regions(layout),
            inferred=inferred,
            warnings=list(layout.warnings),
            diagnostics=diagnostics,
        )

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

    def inspect_resolved(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
    ) -> TemplateResolvedReport:
        """Report final layered values and their originating layers (--resolved). Never raises."""
        try:
            result = self._compiler.inspect_resolved(template, data, format_name, locale)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return TemplateResolvedReport(
                ok=False, diagnostics=[internal_error("Resolve inspect failed", detail=repr(exc))]
            )
        return TemplateResolvedReport(
            ok=result.ok,
            format=result.format_name,
            locale=result.locale,
            direction=result.direction,
            digits=result.digits,
            patches=[
                ResolvedPatchInfo(
                    layer=p.layer, op=p.op, path=p.path, value=p.value, effective=p.effective
                )
                for p in result.patches
            ],
            diagnostics=result.diagnostics,
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
        debug: bool = False,
    ) -> PreviewResult:
        """Render to the stable preview path atomically, with compile/render timings.

        Never raises and never creates a recorded run. On failure the previous preview file is
        left untouched (the atomic temp+replace only runs on success), so a viewer keeps the
        last good image (spec §6.3). With ``debug`` the preview carries the layout overlay.
        """
        try:
            return self._render_preview_inner(
                template, data, format_name, locale, style, dpi, changed_file, debug
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
        debug: bool = False,
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
        diagnostics.extend(layout.warnings)
        backend = self._registries.backends.get(self._default_backend)
        surface = backend.render(layout, RenderOptions(dpi=dpi, debug=debug))
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


# --------------------------------------------------------------- layout report builders
def _logical_edge(edge: str, direction: str) -> str:
    if edge == "start":
        return "left" if direction == "ltr" else "right"
    if edge == "end":
        return "right" if direction == "ltr" else "left"
    return edge


def _edge_value(edge: str, node: LayoutNode) -> float:
    b = node.bounds
    return {
        "top": b.y, "bottom": b.bottom, "center_y": b.center_y,
        "left": b.x, "right": b.right, "center_x": b.center_x,
    }[edge]


def _build_node_report(
    compiled: CompiledNode,
    layout: LayoutNode,
    group_dir: str,
    dpi: int,
    overlaps: list[SiblingOverlap],
    parent_stack: str | None = None,
) -> LayoutNodeReport:
    b = layout.bounds
    pb = layout.paint_bounds
    scale = dpi / 72.0
    overflow = None
    if layout.overflow.kind != "none" or layout.overflow.measured_h_pt > 0.0:
        overflow = OverflowReport(
            kind=layout.overflow.kind,
            measured_w_pt=layout.overflow.measured_w_pt,
            measured_h_pt=layout.overflow.measured_h_pt,
            box_w_pt=layout.overflow.box_w_pt,
            box_h_pt=layout.overflow.box_h_pt,
        )
    anchors = _derive_anchors(compiled, layout, group_dir, parent_stack)

    children_reports: list[LayoutNodeReport] = []
    if isinstance(compiled, CompiledGroup):
        by_id = {c.source_node_id: c for c in layout.children}
        stack_kind = compiled.stack.kind if compiled.stack.kind != "absolute" else None
        for child in compiled.children:
            lchild = by_id.get(child.id)
            if lchild is None:
                continue
            children_reports.append(
                _build_node_report(child, lchild, compiled.direction, dpi, overlaps, stack_kind)
            )
        _collect_overlaps(layout.children, overlaps)

    t = layout.absolute_transform
    return LayoutNodeReport(
        id=layout.source_node_id,
        kind=layout.kind,
        bounds_pt=(b.x, b.y, b.w, b.h),
        bounds_px=(b.x * scale, b.y * scale, b.w * scale, b.h * scale),
        paint_bounds_pt=(pb.x, pb.y, pb.w, pb.h),
        paint_bounds_px=(pb.x * scale, pb.y * scale, pb.w * scale, pb.h * scale),
        absolute_transform=(t.a, t.b, t.c, t.d, t.e, t.f),
        rotate_deg=layout.rotate_deg,
        overflow=overflow,
        anchors=anchors,
        children=children_reports,
    )


def _derive_anchors(
    compiled: CompiledNode, layout: LayoutNode, group_dir: str, parent_stack: str | None
) -> list[AnchorDerivation]:
    if parent_stack is not None and not compiled.constraints.anchors:
        return [
            AnchorDerivation(
                axis="horizontal", edge="—",
                expression=f"positioned by {parent_stack}", resolved_pt=layout.bounds.x,
            ),
            AnchorDerivation(
                axis="vertical", edge="—",
                expression=f"positioned by {parent_stack}", resolved_pt=layout.bounds.y,
            ),
        ]
    out: list[AnchorDerivation] = []
    horizontal = {"left", "right", "center_x"}
    for key, anchor in compiled.constraints.anchors.items():
        phys_key = _logical_edge(key, group_dir)
        axis = "horizontal" if phys_key in horizontal else "vertical"
        ref_edge = _logical_edge(anchor.edge, group_dir)
        # A logical (start/end) reference edge takes its offset in reading order, which the
        # solver flips to -offset under rtl; the printed expression must reflect that flipped
        # math so the derivation string evaluates to the resolved value (CR-7).
        display_offset = anchor.offset_pt
        if anchor.edge in ("start", "end") and group_dir == "rtl":
            display_offset = -display_offset
        sign = "+" if display_offset >= 0 else "-"
        offset = f" {sign} {abs(display_offset):g}pt" if display_offset else ""
        expression = f"{anchor.ref}.{ref_edge}{offset}"
        out.append(
            AnchorDerivation(
                axis=axis, edge=phys_key, expression=expression,
                resolved_pt=_edge_value(phys_key, layout),
            )
        )
    return out


def _collect_overlaps(children: tuple[LayoutNode, ...], overlaps: list[SiblingOverlap]) -> None:
    visible = [c for c in children if c.visible]
    for i in range(len(visible)):
        for j in range(i + 1, len(visible)):
            a, b = visible[i], visible[j]
            # Rotated nodes contribute their post-transform AABB to overlap reporting (CR-14).
            ra, rb = a.paint_bounds, b.paint_bounds
            rect = _intersection(ra, rb)
            if rect is None:
                continue
            # DX-8: a full-bleed backdrop or a parent-fill container trivially overlaps its
            # neighbours; when one node fully contains the other the pair is suppressed as noise
            # so the genuine partial collisions (the real bugs) rise to the top of the report.
            if _contains(ra, rb) or _contains(rb, ra):
                continue
            overlaps.append(
                SiblingOverlap(a=a.source_node_id, b=b.source_node_id, rect_pt=rect)
            )


def _contains(outer: object, inner: object) -> bool:
    """Whether ``outer`` fully contains ``inner`` (small tolerance for quantization)."""
    ox, oy, ow, oh = outer.x, outer.y, outer.w, outer.h  # type: ignore[attr-defined]
    ix, iy, iw, ih = inner.x, inner.y, inner.w, inner.h  # type: ignore[attr-defined]
    eps = 0.01
    return bool(
        ox - eps <= ix
        and oy - eps <= iy
        and ox + ow + eps >= ix + iw
        and oy + oh + eps >= iy + ih
    )


def _intersection(a: object, b: object) -> tuple[float, float, float, float] | None:
    ax, ay, aw, ah = a.x, a.y, a.w, a.h  # type: ignore[attr-defined]
    bx, by, bw, bh = b.x, b.y, b.w, b.h  # type: ignore[attr-defined]
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 - x0 > 0.01 and y1 - y0 > 0.01:
        return (x0, y0, x1 - x0, y1 - y0)
    return None


def _covered_fraction(layout: LayoutDocument, cells: int = 64) -> float:
    """Approximate the fraction of the canvas covered by any leaf node (coarse grid)."""
    w, h = layout.canvas.width_pt, layout.canvas.height_pt
    if w <= 0 or h <= 0:
        return 0.0
    grid = [[False] * cells for _ in range(cells)]

    def mark(node: LayoutNode) -> None:
        if node.children:
            for child in node.children:
                mark(child)
            return
        if not node.visible:
            return
        b = node.bounds
        cx0 = max(0, int(b.x / w * cells))
        cx1 = min(cells, int((b.x + b.w) / w * cells) + 1)
        cy0 = max(0, int(b.y / h * cells))
        cy1 = min(cells, int((b.y + b.h) / h * cells) + 1)
        for cy in range(cy0, cy1):
            for cx in range(cx0, cx1):
                grid[cy][cx] = True

    mark(layout.root)
    covered = sum(row.count(True) for row in grid)
    return round(covered / (cells * cells), 4)


def _free_regions(
    layout: LayoutDocument, cells: int = 64, min_rows: int = 2
) -> list[tuple[float, float, float, float]]:
    """Return maximal full-width empty horizontal bands, largest first (spec §6.1.1).

    Rows of the coarse coverage grid that are entirely uncovered are merged into vertical
    bands; a band is reported when it spans at least ``min_rows`` rows (so trivial slivers are
    dropped). This is the summary that makes an unfilled top/bottom slab obvious.
    """
    w, h = layout.canvas.width_pt, layout.canvas.height_pt
    if w <= 0 or h <= 0:
        return []
    grid = [[False] * cells for _ in range(cells)]

    def mark(node: LayoutNode) -> None:
        if node.children:
            for child in node.children:
                mark(child)
            return
        if not node.visible:
            return
        b = node.bounds
        cx0 = max(0, int(b.x / w * cells))
        cx1 = min(cells, int((b.x + b.w) / w * cells) + 1)
        cy0 = max(0, int(b.y / h * cells))
        cy1 = min(cells, int((b.y + b.h) / h * cells) + 1)
        for cy in range(cy0, cy1):
            for cx in range(cx0, cx1):
                grid[cy][cx] = True

    mark(layout.root)
    empty_rows = [cy for cy in range(cells) if not any(grid[cy])]
    bands: list[tuple[int, int]] = []
    run_start: int | None = None
    prev = -2
    for cy in empty_rows:
        if run_start is None:
            run_start = cy
        elif cy != prev + 1:
            bands.append((run_start, prev))
            run_start = cy
        prev = cy
    if run_start is not None:
        bands.append((run_start, prev))
    row_h = h / cells
    regions = [
        (0.0, round(start * row_h, 2), round(w, 2), round((end - start + 1) * row_h, 2))
        for start, end in bands
        if (end - start + 1) >= min_rows
    ]
    regions.sort(key=lambda r: r[3], reverse=True)
    return regions


LayoutNodeReport.model_rebuild()

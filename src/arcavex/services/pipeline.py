"""The layout → render → export tail of the pipeline, in one place.

The facade (direct render, preview) and the project orchestrator (project renders, reruns,
batch) share exactly this sequence: solve layout, render to a surface, export to a PNG. Keeping
it in one function means a determinism-relevant change (how a surface becomes bytes) can never
apply to one path and not the other. The solver/backend/exporter are passed in as already
constructed components (bootstrap owns the registry), so this module imports no built-ins.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from arcavex.kernel.contracts.types import (
    ExportOptions,
    ExportReport,
    MeasureFn,
    RenderOptions,
    Surface,
)
from arcavex.kernel.diagnostics import Diagnostic
from arcavex.kernel.ir.models import CompiledDocument, LayoutDocument


class _Solver(Protocol):
    def solve(self, document: CompiledDocument, measure: MeasureFn) -> LayoutDocument: ...


class _Backend(Protocol):
    def render(self, layout: LayoutDocument, opts: RenderOptions) -> Surface: ...


class _Exporter(Protocol):
    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport: ...


def render_to_file(
    solver: _Solver,
    backend: _Backend,
    exporter: _Exporter,
    measure: MeasureFn,
    document: CompiledDocument,
    output: Path,
    dpi: int | None,
    debug: bool,
) -> tuple[ExportReport, list[Diagnostic]]:
    """Lay out, render, and export ``document`` to ``output``; return the report and warnings.

    Layout warnings (missing glyphs, fit non-convergence) are returned so the caller can surface
    them alongside compile diagnostics. The exporter writes atomically and reports the content
    hash, which is the determinism anchor for reruns and diffs.
    """
    layout = solver.solve(document, measure)
    warnings = list(layout.warnings)
    surface = backend.render(layout, RenderOptions(dpi=dpi, debug=debug))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = exporter.export(surface, output, ExportOptions(dpi=dpi))
    return report, warnings

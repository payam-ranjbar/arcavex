"""The layout → render → export tail of the pipeline, in one place.

The facade (direct render, preview) and the project orchestrator (project renders, reruns,
batch) share exactly this sequence: solve layout, render to a surface, export to a PNG. Keeping
it in one function means a determinism-relevant change (how a surface becomes bytes) can never
apply to one path and not the other. The solver/backend/exporter are passed in as already
constructed components (bootstrap owns the registry), so this module imports no built-ins.
"""

from __future__ import annotations

import time
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


class _Budget(Protocol):
    def check_surface(self, width_px: int, height_px: int, *, file: str | None = ...) -> None: ...

    def check_wall_ms(self, elapsed_ms: float, *, file: str | None = ...) -> None: ...


def render_to_file(
    solver: _Solver,
    backend: _Backend,
    exporter: _Exporter,
    measure: MeasureFn,
    document: CompiledDocument,
    output: Path,
    dpi: int | None,
    debug: bool,
    budget: _Budget | None = None,
    engine_version: str = "",
) -> tuple[ExportReport, list[Diagnostic]]:
    """Lay out, render, and export ``document`` to ``output``; return the report and warnings.

    Layout warnings (missing glyphs, fit non-convergence) are returned so the caller can surface
    them alongside compile diagnostics. The exporter writes atomically and reports the content
    hash, which is the determinism anchor for reruns and diffs. When a ``budget`` is supplied the
    render surface is checked against the per-render resource limits (spec §8.3) before it is
    allocated and again for wall-clock after it completes; the export options carry the physical
    page geometry the PDF exporter needs and the engine version embedded as stable metadata.
    """
    canvas = document.canvas
    effective_dpi = dpi or canvas.dpi
    width_px = max(1, round(canvas.width_pt * effective_dpi / 72.0))
    height_px = max(1, round(canvas.height_pt * effective_dpi / 72.0))
    if budget is not None:
        budget.check_surface(width_px, height_px)
    layout = solver.solve(document, measure)
    warnings = list(layout.warnings)
    started = time.monotonic()
    surface = backend.render(layout, RenderOptions(dpi=dpi, debug=debug))
    if budget is not None:
        budget.check_wall_ms((time.monotonic() - started) * 1000.0)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    opts = ExportOptions(
        dpi=dpi,
        page_width_pt=canvas.width_pt,
        page_height_pt=canvas.height_pt,
        bleed_pt=canvas.bleed_pt,
        engine_version=engine_version,
    )
    report = exporter.export(surface, output, opts)
    return report, warnings

"""Export tail for orchestrated renders.

The document → surface step is ``kernel.pipeline.layout_and_render``, shared with the facade.
This module adds the direct-to-path export the orchestrator needs. The solver, backend and
exporter arrive already constructed (bootstrap owns the registry), so nothing here imports a
built-in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from arcavex.kernel.contracts.types import (
    ExportOptions,
    ExportReport,
    MeasureFn,
    Surface,
)
from arcavex.kernel.diagnostics import Diagnostic
from arcavex.kernel.ir.models import CompiledDocument
from arcavex.kernel.pipeline import Backend, Budget, Solver, layout_and_render


class _Exporter(Protocol):
    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport: ...


def render_to_file(
    solver: Solver,
    backend: Backend,
    exporter: _Exporter,
    measure: MeasureFn,
    document: CompiledDocument,
    output: Path,
    dpi: int | None,
    debug: bool,
    budget: Budget | None = None,
    engine_version: str = "",
) -> tuple[ExportReport, list[Diagnostic]]:
    """Lay out, render, and export ``document`` to ``output``; return the report and warnings.

    The exporter writes atomically and reports the content hash, which is the determinism anchor
    for reruns and diffs. The export options carry the physical page geometry the PDF exporter
    needs and the engine version embedded as stable metadata.
    """
    surface, _, warnings = layout_and_render(
        solver=solver,
        backend=backend,
        measure=measure,
        document=document,
        dpi=dpi,
        debug=debug,
        budget=budget,
    )
    canvas = document.canvas
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

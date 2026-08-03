"""The document → surface step, shared by every render path.

Layout and rendering determine the output bytes, so all callers run one sequence: budget
pre-flight, solve, render, wall-clock budget. Export stays with the caller, which legitimately
differs (encoder options for a direct export, temp-file replace for a preview).

It lives in the kernel because it depends only on kernel contracts and IR, and because
``kernel.api`` is a caller and cannot import services.
"""

from __future__ import annotations

import time
from typing import Protocol

from arcavex.kernel.contracts.types import MeasureFn, RenderOptions, Surface
from arcavex.kernel.diagnostics import Diagnostic
from arcavex.kernel.ir.models import CompiledDocument, LayoutDocument


class Solver(Protocol):
    """Resolves a compiled document into absolute geometry."""

    def solve(self, document: CompiledDocument, measure: MeasureFn) -> LayoutDocument: ...


class Backend(Protocol):
    """Paints a laid-out document onto a surface."""

    def render(self, layout: LayoutDocument, opts: RenderOptions) -> Surface: ...


class Budget(Protocol):
    """Per-render resource limits (spec §8.3)."""

    def check_surface(self, width_px: int, height_px: int, *, file: str | None = ...) -> None: ...

    def check_wall_ms(self, elapsed_ms: float, *, file: str | None = ...) -> None: ...


def surface_px(document: CompiledDocument, dpi: int | None) -> tuple[int, int]:
    """Return the pixel dimensions a render of ``document`` at ``dpi`` will allocate."""
    canvas = document.canvas
    effective_dpi = dpi or canvas.dpi
    return (
        max(1, round(canvas.width_pt * effective_dpi / 72.0)),
        max(1, round(canvas.height_pt * effective_dpi / 72.0)),
    )


def layout_and_render(
    *,
    solver: Solver,
    backend: Backend,
    measure: MeasureFn,
    document: CompiledDocument,
    dpi: int | None,
    debug: bool = False,
    budget: Budget | None = None,
    file: str | None = None,
) -> tuple[Surface, LayoutDocument, list[Diagnostic]]:
    """Solve and render ``document``, returning the surface, layout, and layout warnings.

    The surface budget is checked before allocation and the wall-clock budget after the render.
    ``file`` locates both budget diagnostics on the template that produced the canvas.

    Layout warnings (missing glyphs, fit non-convergence) are returned rather than raised so the
    caller can surface them alongside compile diagnostics.
    """
    if budget is not None:
        width_px, height_px = surface_px(document, dpi)
        budget.check_surface(width_px, height_px, file=file)
    layout = solver.solve(document, measure)
    started = time.monotonic()
    surface = backend.render(layout, RenderOptions(dpi=dpi, debug=debug))
    if budget is not None:
        budget.check_wall_ms((time.monotonic() - started) * 1000.0, file=file)
    return surface, layout, list(layout.warnings)

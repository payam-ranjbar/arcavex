"""Per-render resource budget tests (spec §8.3): pre-flight refusal and located diagnostics.

An oversized render must be refused with a located ``ARC-RND`` diagnostic before the surface is
allocated, and the CLI must map that to exit 4. These tests cover the budget checks directly and
the facade path that enforces them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.clients.cli import _exit_code_for
from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.budgets import RenderBudget

_HUGE_TEMPLATE = """\
version: 0.1.0
formats:
  huge:
    canvas: {width: 40000px, height: 40000px, dpi: 72}
root:
  type: group
  id: root
  children:
    - id: bg
      type: shape
      shape: rect
      style: {fill: "#123456"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
"""


def test_within_budget_passes() -> None:
    RenderBudget().check_surface(5000, 7000)  # A4 @ 600 dpi, comfortably inside


def test_output_dimension_budget() -> None:
    with pytest.raises(DiagnosticError) as exc:
        RenderBudget(max_dimension=1000).check_surface(2000, 500, file="t.yaml")
    diag = exc.value.diagnostics[0]
    assert diag.code == "ARC-RND-020"
    assert diag.source is not None and diag.source.file == "t.yaml"  # located


def test_pixel_budget() -> None:
    with pytest.raises(DiagnosticError) as exc:
        RenderBudget(max_dimension=100_000, max_pixels=1_000_000).check_surface(2000, 2000)
    assert exc.value.diagnostics[0].code == "ARC-RND-021"


def test_surface_memory_budget() -> None:
    with pytest.raises(DiagnosticError) as exc:
        RenderBudget(
            max_dimension=100_000, max_pixels=10_000_000_000, max_surface_bytes=1_000_000
        ).check_surface(2000, 2000)
    assert exc.value.diagnostics[0].code == "ARC-RND-022"


def test_wall_clock_budget() -> None:
    with pytest.raises(DiagnosticError) as exc:
        RenderBudget(max_wall_ms=10).check_wall_ms(50.0)
    assert exc.value.diagnostics[0].code == "ARC-RND-023"


def test_from_config_overrides_defaults() -> None:
    budget = RenderBudget.from_config({"budgets": {"max_dimension": 123, "max_wall_ms": 45}})
    assert budget.max_dimension == 123
    assert budget.max_wall_ms == 45
    # A malformed value falls back to the default rather than crashing.
    assert RenderBudget.from_config({"budgets": {"max_pixels": "nope"}}).max_pixels > 0


def test_facade_refuses_oversized_render(tmp_path: Path) -> None:
    template = tmp_path / "huge.yaml"
    template.write_text(_HUGE_TEMPLATE, encoding="utf-8")
    facade = build_facade()
    result = facade.render_file(template, format_name="huge", output=tmp_path / "huge.png")
    assert not result.ok
    codes = [d.code for d in result.diagnostics]
    assert "ARC-RND-020" in codes
    # The CLI maps a budget diagnostic to exit 4.
    assert _exit_code_for(result.diagnostics, result.ok) == 4
    assert not (tmp_path / "huge.png").exists()  # nothing written

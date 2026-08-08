"""Mask generator tests: path construction, param validation, and pixel treatment."""

from __future__ import annotations

from pathlib import Path

import pytest
import skia  # type: ignore[import-untyped]
from pydantic import ValidationError

from arcavex.builtin.masks_core.masks import (
    CircleMask,
    DiamondGridMask,
    DiamondGridParams,
    RoundedRectMask,
    RoundedRectParams,
    builtin_masks,
)
from arcavex.kernel.ir.units import Rect
from arcavex.services.template.compiler import Compiler


def test_builtin_masks_registered() -> None:
    names = {m.name for m in builtin_masks()}
    assert names == {"rounded_rect", "circle", "diamond_grid"}


def test_rounded_rect_builds_within_bounds() -> None:
    path = RoundedRectMask().build(RoundedRectParams(radius=10.0), Rect(0, 0, 100, 60))
    b = path.getBounds()
    assert (round(b.width()), round(b.height())) == (100, 60)


def test_diamond_grid_pt_units_only() -> None:
    # A pixel unit is rejected so masks stay DPI-independent.
    with pytest.raises(ValidationError):
        DiamondGridParams(cell="90px")  # type: ignore[arg-type]
    # pt and mm are accepted.
    assert DiamondGridParams(cell="90pt").cell == 90.0


def test_diamond_grid_cells_and_gutters() -> None:
    """Sampling: a cell centre shows the clipped content; a gutter shows the background."""
    size = 300
    surface = skia.Surface(size, size)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorWHITE)  # background
    path = DiamondGridMask().build(
        DiamondGridParams(cell=60, gutter=16, angle=45), Rect(0, 0, size, size)
    )
    canvas.save()
    canvas.clipPath(path, skia.ClipOp.kIntersect, True)
    paint = skia.Paint()
    paint.setColor(skia.ColorRED)  # image content stand-in
    canvas.drawRect(skia.Rect.MakeXYWH(0, 0, size, size), paint)
    canvas.restore()
    # The colorType must be stated: toarray()'s default follows the platform's native surface
    # order, which is BGRA on Windows and RGBA on macOS arm64, so a channel index means nothing
    # without it. Every production call site already passes one.
    arr = surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)

    def is_red(x: int, y: int) -> bool:
        px = arr[y, x]
        return px[0] > 180 and px[2] < 80

    def is_white(x: int, y: int) -> bool:
        px = arr[y, x]
        return px[0] > 230 and px[1] > 230 and px[2] > 230

    row = size // 2
    reds = sum(1 for x in range(size) if is_red(x, row))
    whites = sum(1 for x in range(size) if is_white(x, row))
    assert reds > 20, "expected image content inside cells"
    assert whites > 20, "expected background visible through gutters"


def test_circle_is_inscribed_ellipse() -> None:
    path = CircleMask().build(CircleMask.param_schema(), Rect(10, 10, 80, 40))
    b = path.getBounds()
    assert round(b.width()) == 80 and round(b.height()) == 40


# ------------------------------------------------------------ compiler param validation
_MASK_TPL = """
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
root:
  type: group
  id: root
  children:
    - id: box
      type: shape
      shape: rect
      mask: {component: %s, params: %s}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
"""


def _mask_schema(name: str):  # noqa: ANN202
    masks = {m.name: m for m in builtin_masks()}
    return masks[name].param_schema if name in masks else None


def _compiler() -> Compiler:
    names = frozenset(m.name for m in builtin_masks())
    return Compiler(masks=names, mask_schema=_mask_schema)


def test_valid_mask_compiles(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    template.write_text(_MASK_TPL % ("diamond_grid", "{cell: 40pt, gutter: 4pt}"), encoding="utf-8")
    result = _compiler().compile(template, None, "square", None, None)
    assert result.document is not None, result.diagnostics
    assert result.document.root.children[0].mask is not None


def test_unknown_mask_component_errors(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    template.write_text(_MASK_TPL % ("hexagons", "{}"), encoding="utf-8")
    result = _compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-FX-901" for d in result.diagnostics)


def test_invalid_mask_params_errors(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    # A negative cell fails the schema's gt=0 constraint.
    template.write_text(_MASK_TPL % ("diamond_grid", "{cell: -5pt}"), encoding="utf-8")
    result = _compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-FX-902" for d in result.diagnostics)

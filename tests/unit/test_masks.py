"""Mask generator tests: path construction, param validation, and pixel treatment."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import skia  # type: ignore[import-untyped]
from pydantic import ValidationError

from arcavex.bootstrap import build_facade
from arcavex.builtin.masks_core.masks import (
    CircleMask,
    DiamondGridMask,
    DiamondGridParams,
    LinearFadeMask,
    LinearFadeParams,
    RoundedRectMask,
    RoundedRectParams,
    builtin_masks,
)
from arcavex.kernel.ir.units import Rect
from arcavex.services.template.compiler import Compiler

_SUBJECT = (
    Path(__file__).resolve().parents[2] / "tests" / "golden" / "fixtures" / "subject.png"
)


def test_builtin_masks_registered() -> None:
    names = {m.name for m in builtin_masks()}
    assert names == {"rounded_rect", "circle", "diamond_grid", "linear_fade"}


def test_rounded_rect_builds_within_bounds() -> None:
    path = RoundedRectMask().build(RoundedRectParams(radius=10.0), Rect(0, 0, 100, 60))
    b = path.getBounds()
    assert (round(b.width()), round(b.height())) == (100, 60)


def test_diamond_grid_absolute_units() -> None:
    # Pixels normalize at the canvas DPI; percentages have no absolute basis.
    model = DiamondGridParams.model_validate({"cell": "90px"}, context={"dpi": 144})
    assert model.cell == 45.0
    with pytest.raises(ValidationError):
        DiamondGridParams(cell="90%")  # type: ignore[arg-type]
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


# ------------------------------------------------------------------- linear_fade
_FADE_TPL = """
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
root:
  type: group
  id: root
  children:
    - id: photo
      type: image
      asset: %s
      fit: fill
%s      mask: {component: linear_fade, params: %s}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
"""


def _render_fade(tmp_path: Path, params: str, effects: str = "") -> np.ndarray:
    """Render the opaque subject image under a ``linear_fade`` mask, straight-alpha RGBA."""
    template = tmp_path / "fade.yaml"
    template.write_text(
        _FADE_TPL % (_SUBJECT.as_posix(), effects, params), encoding="utf-8"
    )
    out = tmp_path / "fade.png"
    result = build_facade().render_file(template, format_name="square", output=out)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    # State the colorType: the default follows the platform's native surface order.
    image = skia.Image.open(str(out))
    return image.toarray(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType)


def test_linear_fade_renders_a_vertical_alpha_gradient(tmp_path: Path) -> None:
    """A rendered photo is opaque at the top, about half in the middle, clear at the bottom."""
    arr = _render_fade(tmp_path, "{direction: to_bottom, start: 0.0, end: 1.0}")
    assert arr[2, 100, 3] >= 250
    assert abs(int(arr[100, 100, 3]) - 128) <= 3
    assert arr[197, 100, 3] <= 5
    # A vertical fade leaves the horizontal axis untouched.
    assert abs(int(arr[100, 5, 3]) - 128) <= 3
    assert abs(int(arr[100, 194, 3]) - 128) <= 3


def test_linear_fade_direction_to_right_fades_horizontally(tmp_path: Path) -> None:
    arr = _render_fade(tmp_path, "{direction: to_right, start: 0.0, end: 1.0}")
    assert arr[100, 2, 3] >= 250
    assert abs(int(arr[100, 100, 3]) - 128) <= 3
    assert arr[100, 197, 3] <= 5
    assert abs(int(arr[5, 100, 3]) - 128) <= 3


def test_linear_fade_params_validate_fractions_and_order() -> None:
    model = LinearFadeParams.model_validate(
        {"direction": "to_bottom", "start": "25%", "end": 1.0}
    )
    assert model.start == pytest.approx(0.25)
    assert model.end == pytest.approx(1.0)
    with pytest.raises(ValidationError):  # reversed range
        LinearFadeParams(start=0.8, end=0.2)
    with pytest.raises(ValidationError):  # unknown direction
        LinearFadeParams(direction="diagonal")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):  # a fraction outside [0, 1]
        LinearFadeParams(start="120%")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):  # unknown params are rejected
        LinearFadeParams.model_validate({"direction": "to_bottom", "junk": 1})


def test_linear_fade_builds_a_shader_and_a_fallback_path() -> None:
    """The generator opts into the alpha shader for every direction; ``build`` stays full-bounds."""
    mask = LinearFadeMask()
    path = mask.build(LinearFadeParams(), Rect(0, 0, 100, 80))
    b = path.getBounds()
    assert (round(b.width()), round(b.height())) == (100, 80)
    for direction in ("to_bottom", "to_top", "to_left", "to_right"):
        shader = mask.build_alpha(LinearFadeParams(direction=direction), Rect(0, 0, 100, 80))
        assert isinstance(shader, skia.Shader)


def test_valid_linear_fade_mask_compiles(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    template.write_text(
        _MASK_TPL % ("linear_fade", "{direction: to_top, start: 10%, end: 90%}"),
        encoding="utf-8",
    )
    result = _compiler().compile(template, None, "square", None, None)
    assert result.document is not None, result.diagnostics
    mask = result.document.root.children[0].mask
    assert mask is not None and mask.component == "linear_fade"
    assert mask.params == {"direction": "to_top", "start": 0.1, "end": 0.9}


def test_invalid_linear_fade_direction_errors(tmp_path: Path) -> None:
    """An unknown fade direction is a located ARC-FX-902 at compile time, not at render."""
    template = tmp_path / "t.yaml"
    template.write_text(_MASK_TPL % ("linear_fade", "{direction: sideways}"), encoding="utf-8")
    result = _compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-FX-902" for d in result.diagnostics)


def test_linear_fade_applies_before_effects(tmp_path: Path) -> None:
    """An alpha mask is baked into the element before the effect plan runs (the effects path)."""
    effects = "      effects:\n        - {name: grade, params: {saturation: 0.5}}\n"
    arr = _render_fade(tmp_path, "{direction: to_bottom, start: 0.0, end: 1.0}", effects)
    assert arr[2, 100, 3] >= 250
    assert abs(int(arr[100, 100, 3]) - 128) <= 3
    assert arr[197, 100, 3] <= 5


def test_linear_fade_render_is_deterministic(tmp_path: Path) -> None:
    """The saveLayer + DstIn path must be byte-stable across renders."""
    first = _render_fade(tmp_path, "{direction: to_bottom, start: 0.1, end: 0.85}")
    second = _render_fade(tmp_path, "{direction: to_bottom, start: 0.1, end: 0.85}")
    assert (first == second).all()

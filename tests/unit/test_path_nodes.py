"""Path nodes: SVG ``d`` parsing, located rejection of bad data, and painted pixels.

A ``path`` node validated, rendered with exit 0, and painted nothing: the solver resolved no
content for it and the backend had no path branch. These tests pin the contract the schema doc
promises — ``d`` is SVG path data in pixels from the node's top-left, painted by the style's
fill and stroke, with geometry effects applied to its outline — and that malformed data is a
located ``ARC-TPL-042`` at validation time rather than a blank render or an exception.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import skia  # type: ignore[import-untyped]

from arcavex.bootstrap import build_facade
from arcavex.kernel.ir.models import CompiledPath
from arcavex.kernel.ir.svgpath import PathCommand, SvgPathError, parse_svg_path
from arcavex.services.template.compiler import Compiler

_HEAD = """version: 0.1.0
formats:
  sq: {canvas: {width: 200px, height: 200px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: bg
      type: shape
      shape: rect
      style: {fill: "#FFFFFF"}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
"""
_FULL_BOX = "constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}"


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201
    return build_facade()


def _write(tmp_path: Path, body: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "t.yaml"
    path.write_text(_HEAD + body, encoding="utf-8")
    return path


def _render(facade, tmp_path: Path, body: str) -> np.ndarray:  # noqa: ANN001
    out = tmp_path / "out.png"
    result = facade.render_file(_write(tmp_path, body), format_name="sq", output=out)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    image = skia.Image.open(str(out))
    array: np.ndarray = image.toarray(
        colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
    )
    return array


def _non_white(array: np.ndarray) -> int:
    return int(np.count_nonzero(np.any(array[:, :, :3] != 255, axis=2)))


def _compile_error(tmp_path: Path, body: str):  # noqa: ANN202
    result = Compiler().compile(_write(tmp_path, body), None, "sq", None, None)
    errors = [d for d in result.diagnostics if d.is_error()]
    assert errors, "expected a compile error"
    return errors[0]


# ------------------------------------------------------------------------------- parser
def test_parser_normalizes_relative_and_shorthand_commands() -> None:
    commands = parse_svg_path("m 10 20 h 30 v 40 l -5,-5 z")
    assert commands == (
        PathCommand(op="M", args=(10.0, 20.0)),
        PathCommand(op="L", args=(40.0, 20.0)),
        PathCommand(op="L", args=(40.0, 60.0)),
        PathCommand(op="L", args=(35.0, 55.0)),
        PathCommand(op="Z"),
    )


def test_parser_implicit_repeats_and_compact_numbers() -> None:
    # A repeated move draws lines; "10-20" and "1.5.5" are two numbers each; exponents parse.
    commands = parse_svg_path("M0,0 10-20 1.5.5 L1e1 2E-1")
    assert [c.op for c in commands] == ["M", "L", "L", "L"]
    assert commands[1].args == (10.0, -20.0)
    assert commands[2].args == (1.5, 0.5)
    assert commands[3].args == (10.0, 0.2)


def test_parser_reflects_smooth_control_points() -> None:
    commands = parse_svg_path("M 0 0 C 10 10 20 10 30 0 S 50 -10 60 0 Q 70 10 80 0 T 100 0")
    assert commands[2] == PathCommand(op="C", args=(40.0, -10.0, 50.0, -10.0, 60.0, 0.0))
    assert commands[4] == PathCommand(op="Q", args=(90.0, -10.0, 100.0, 0.0))


def test_parser_reads_arc_flags_without_separators() -> None:
    commands = parse_svg_path("M 0 0 a 25 25 -30 0150 10")
    assert commands[1] == PathCommand(op="A", args=(25.0, 25.0, -30.0, 0.0, 1.0, 50.0, 10.0))


def test_parser_scales_lengths_but_not_angles_or_flags() -> None:
    arc = PathCommand(op="A", args=(10.0, 20.0, 45.0, 1.0, 0.0, 30.0, 40.0)).scaled(0.5)
    assert arc.args == (5.0, 10.0, 45.0, 1.0, 0.0, 15.0, 20.0)


@pytest.mark.parametrize(
    ("data", "token", "reason"),
    [
        ("", "end of data", "empty"),
        ("L 10 10", "L", "start with a move"),
        ("M 20 20 X 5 5", "X", "unknown path command"),
        ("M 20 20 L 180", "end of data", "needs 2 numbers"),
        ("M 0 0 A 10 10 0 2 0 5 5", "2", "flags must be 0 or 1"),
        ("M 0 0 Z 5 5", "5", "takes no numbers"),
        ("M 0 0 L 1e999 0", "1e999", "out of range"),
    ],
)
def test_parser_rejects_malformed_data_naming_the_token(
    data: str, token: str, reason: str
) -> None:
    with pytest.raises(SvgPathError) as info:
        parse_svg_path(data)
    assert info.value.token == token
    assert reason in info.value.reason


# ----------------------------------------------------------------------------- compiler
def test_d_compiles_to_point_commands_at_canvas_dpi(tmp_path: Path) -> None:
    template = _write(
        tmp_path, f"    - id: p\n      type: path\n      d: 'M 0 0 L 96 0'\n      {_FULL_BOX}\n"
    )
    result = Compiler().compile(template, None, "sq", None, None)
    assert result.document is not None, [d.model_dump() for d in result.diagnostics]
    node = result.document.root.children[1]
    assert isinstance(node, CompiledPath)
    assert node.d == "M 0 0 L 96 0"
    # 96 px at 96 dpi is one inch: 72 pt.
    assert node.commands == (
        PathCommand(op="M", args=(0.0, 0.0)),
        PathCommand(op="L", args=(72.0, 0.0)),
    )


def test_malformed_d_is_located_and_quotes_the_token(tmp_path: Path) -> None:
    diag = _compile_error(
        tmp_path, f"    - id: p\n      type: path\n      d: 'M 20 20 X 5 5'\n      {_FULL_BOX}\n"
    )
    assert diag.code == "ARC-TPL-042"
    assert diag.source is not None
    assert diag.source.keypath == "root.children[1].d"
    assert diag.source.line == 15
    assert "'X'" in (diag.hint or "")


def test_missing_d_is_located(tmp_path: Path) -> None:
    diag = _compile_error(tmp_path, f"    - id: p\n      type: path\n      {_FULL_BOX}\n")
    assert diag.code == "ARC-TPL-042"
    assert diag.source is not None and diag.source.keypath == "root.children[1].d"
    assert "no path data" in diag.message


# ------------------------------------------------------------------------------ pixels
def test_path_paints_fill_inside_and_stroke_on_its_edge(facade, tmp_path: Path) -> None:  # noqa: ANN001
    array = _render(
        facade,
        tmp_path,
        "    - id: p\n      type: path\n"
        "      d: 'M 20 20 L 180 20 L 180 180 L 20 180 Z'\n"
        "      style: {fill: '#FF0000', stroke: '#0000FF', stroke_width: 6px}\n"
        f"      {_FULL_BOX}\n",
    )
    assert tuple(array[100, 100]) == (255, 0, 0, 255)  # fill, well inside
    edge = array[100, 20]  # the stroke straddles x=20
    assert edge[2] > 200 and edge[0] < 60, tuple(edge)
    assert tuple(array[100, 5]) == (255, 255, 255, 255)  # untouched background
    assert tuple(array[10, 10]) == (255, 255, 255, 255)


def test_path_coordinates_are_pixels_from_the_node_box_origin(facade, tmp_path: Path) -> None:  # noqa: ANN001
    # The same square drawn in a box offset by (100, 100) lands 100 px further down and right.
    array = _render(
        facade,
        tmp_path,
        "    - id: p\n      type: path\n"
        "      d: 'M 0 0 L 60 0 L 60 60 L 0 60 Z'\n"
        "      style: {fill: '#FF0000'}\n"
        "      constraints: {anchor: {top: parent.top+100px, left: parent.left+100px}, "
        "size: {w: 60px, h: 60px}}\n",
    )
    assert tuple(array[130, 130]) == (255, 0, 0, 255)
    assert tuple(array[30, 30]) == (255, 255, 255, 255)


def test_relative_commands_and_arcs_render(facade, tmp_path: Path) -> None:  # noqa: ANN001
    array = _render(
        facade,
        tmp_path,
        "    - id: p\n      type: path\n"
        "      d: 'm 40 120 l 40 -60 a 40 40 0 0 1 80 0 l 20 60 z'\n"
        "      style: {fill: '#00AA00'}\n"
        f"      {_FULL_BOX}\n",
    )
    assert _non_white(array) > 3000
    # The arc bulges above the chord between its end points, so a pixel there is painted.
    assert tuple(array[40, 120])[1] > 100


def test_geometry_effect_applies_to_the_path_outline(facade, tmp_path: Path) -> None:  # noqa: ANN001
    body = (
        "    - id: p\n      type: path\n"
        "      d: 'M 20 20 L 180 20 L 180 180 L 20 180 Z'\n"
        "      style: {fill: '#FF0000'}\n"
        "{effects}"
        f"      {_FULL_BOX}\n"
    )
    plain = _render(facade, tmp_path / "plain", body.replace("{effects}", ""))
    torn = _render(
        facade,
        tmp_path / "torn",
        body.replace(
            "{effects}", "      effects: [{name: torn-paper, params: {amplitude: 6, segment: 8}}]\n"
        ),
    )
    assert _non_white(torn) > 3000
    assert tuple(torn[100, 100]) == (255, 0, 0, 255)
    assert not np.array_equal(plain, torn)


def test_path_honours_opacity_like_a_shape(facade, tmp_path: Path) -> None:  # noqa: ANN001
    array = _render(
        facade,
        tmp_path,
        "    - id: p\n      type: path\n"
        "      d: 'M 20 20 L 180 20 L 180 180 L 20 180 Z'\n"
        "      style: {fill: '#FF0000', opacity: 0.5}\n"
        f"      {_FULL_BOX}\n",
    )
    r, g, b, _ = (int(v) for v in array[100, 100])
    assert r == 255 and 120 <= g <= 135 and 120 <= b <= 135

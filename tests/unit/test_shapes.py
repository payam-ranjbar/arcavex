"""Shape-generator tests: parametric paths, QR determinism, and located errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.builtin.shapes_core import builtin_shapes
from arcavex.kernel.ir.units import Rect


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201
    return build_facade()


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "t.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_generators_build_non_empty_paths() -> None:
    bounds = Rect(0, 0, 200, 200)
    for gen in builtin_shapes():
        params = (
            gen.param_schema(data="hello")
            if gen.name == "qr_code"
            else gen.param_schema()
        )
        path = gen.build(params, bounds)
        assert not path.isEmpty()
        b = path.getBounds()
        # The path stays within (or on) the node bounds.
        assert b.left() >= -0.5 and b.top() >= -0.5
        assert b.right() <= 200.5 and b.bottom() <= 200.5


def test_starburst_point_count_changes_path() -> None:
    from arcavex.builtin.shapes_core.shapes import Starburst, StarburstParams

    s = Starburst()
    p8 = s.build(StarburstParams(points=8), Rect(0, 0, 100, 100))
    p20 = s.build(StarburstParams(points=20), Rect(0, 0, 100, 100))
    assert p8.countPoints() != p20.countPoints()


def test_qr_code_is_deterministic() -> None:
    from arcavex.builtin.shapes_core.shapes import QrCode, QrCodeParams

    gen = QrCode()
    bounds = Rect(0, 0, 300, 300)
    a = gen.build(QrCodeParams(data="https://arcavex.dev"), bounds)
    b = gen.build(QrCodeParams(data="https://arcavex.dev"), bounds)
    c = gen.build(QrCodeParams(data="https://example.com"), bounds)
    assert a.countPoints() == b.countPoints()
    # Different payloads produce a different module layout (hence a different point count).
    assert a.countPoints() != c.countPoints()


def test_shape_generator_renders(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 200px, height: 200px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: burst\n      type: shape\n      generator: starburst\n"
        "      params: {points: 14, inner_ratio: 0.5}\n"
        "      style: {fill: '#ff3ea5'}\n"
        "      constraints: {anchor: {center_x: parent.center_x, center_y: parent.center_y}, "
            "size: {w: 80%, h: 80%}}\n",
    )
    out = tmp_path / "out.png"
    result = facade.render_file(template, format_name="sq", output=out)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert out.is_file()


def test_unknown_generator_is_located(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      generator: sunburst\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    diags = facade.validate_template(template, format_name="sq")
    d = next(d for d in diags if d.code == "ARC-FX-913")
    assert d.source is not None and "sunburst" in d.message


def test_invalid_generator_params_located(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      generator: starburst\n"
        "      params: {points: 2}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    diags = facade.validate_template(template, format_name="sq")
    assert any(d.code == "ARC-FX-912" for d in diags)


def test_qr_code_data_from_expression(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 200px, height: 200px, dpi: 96}}}\n"
        "variables: {link: {type: string, default: 'https://arcavex.dev'}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: qr\n      type: shape\n      generator: qr_code\n"
        "      params: {data: '{{ link }}', quiet_zone: 2}\n"
        "      style: {fill: '#000000'}\n"
        "      constraints: {anchor: {center_x: parent.center_x, center_y: parent.center_y}, "
            "size: {w: 80%, h: 80%}}\n",
    )
    out = tmp_path / "qr.png"
    result = facade.render_file(template, format_name="sq", output=out)
    assert result.ok, [d.model_dump() for d in result.diagnostics]

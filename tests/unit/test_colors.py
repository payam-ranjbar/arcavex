"""Color parsing tests."""

from __future__ import annotations

import math

import pytest

from arcavex.kernel.ir.colors import Color


def _close(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(math.isclose(x, y, abs_tol=1e-6) for x, y in zip(a, b, strict=True))


def test_hex_rgb() -> None:
    assert _close(Color.parse("#fff").as_tuple(), (1.0, 1.0, 1.0, 1.0))
    assert _close(Color.parse("#000").as_tuple(), (0.0, 0.0, 0.0, 1.0))


def test_hex_rrggbb() -> None:
    assert _close(Color.parse("#ff0000").as_tuple(), (1.0, 0.0, 0.0, 1.0))


def test_hex_rrggbbaa() -> None:
    c = Color.parse("#00ff0080")
    assert _close(c.as_tuple(), (0.0, 1.0, 0.0, 128 / 255))


def test_hex_rgba_short() -> None:
    c = Color.parse("#0f08")
    assert _close(c.as_tuple(), (0.0, 1.0, 0.0, 136 / 255))


def test_rgb_func() -> None:
    assert _close(Color.parse("rgb(255, 0, 0)").as_tuple(), (1.0, 0.0, 0.0, 1.0))


def test_rgba_func() -> None:
    assert _close(Color.parse("rgba(0, 0, 255, 0.5)").as_tuple(), (0.0, 0.0, 1.0, 0.5))


def test_named() -> None:
    assert _close(Color.parse("white").as_tuple(), (1.0, 1.0, 1.0, 1.0))
    assert _close(Color.parse("transparent").as_tuple(), (0.0, 0.0, 0.0, 0.0))


def test_invalid() -> None:
    with pytest.raises(ValueError):
        Color.parse("#12345")
    with pytest.raises(ValueError):
        Color.parse("notacolor")


def test_canonical_stable() -> None:
    assert Color.parse("#ff0000").canonical() == Color.parse("rgb(255,0,0)").canonical()


def test_rgb_out_of_range_rejected() -> None:
    """CR-18: out-of-range channels are diagnosed, not silently clamped."""
    with pytest.raises(ValueError):
        Color.parse("rgb(300, 0, 0)")
    with pytest.raises(ValueError):
        Color.parse("rgba(0, 0, 0, 2)")


def test_none_is_an_alias_of_transparent() -> None:
    """'none' is how CSS and SVG spell no paint; refusing it read as 'a shape must be filled'."""
    assert Color.parse("none").as_tuple() == Color.parse("transparent").as_tuple()
    assert Color.parse("NONE").a == 0.0
    assert Color.parse("none").canonical() == Color.parse("transparent").canonical()


def test_fill_none_compiles_to_a_stroke_only_shape(tmp_path) -> None:  # noqa: ANN001
    from arcavex.kernel.ir.models import CompiledShape
    from arcavex.services.template.compiler import Compiler

    template = tmp_path / "t.yaml"
    template.write_text(
        """\
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: frame
      type: shape
      shape: rect
      style: {fill: none, stroke: "#ffffff", stroke_width: 4px}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
""",
        encoding="utf-8",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None, [d.model_dump() for d in result.diagnostics]
    frame = result.document.root.children[0]
    assert isinstance(frame, CompiledShape)
    assert frame.style.fill == (0.0, 0.0, 0.0, 0.0)
    assert frame.style.stroke == (1.0, 1.0, 1.0, 1.0)

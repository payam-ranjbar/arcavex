"""Opacity fidelity: a plain node fades the same way its effects-path twin does.

``style.opacity`` was honoured by shapes and images on the direct paint path and by every node
kind on the effects path (the element composites back at that alpha), but a plain text node
rendered pure ink and a plain group did not pass its opacity to its children. These tests pin
the fix and its invariant: with or without an ``effects:`` list, the same input produces the
same bytes. ``blur`` at radius 0 is a proven no-op, so it stands in for "the effects path".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import skia  # type: ignore[import-untyped]

from arcavex.bootstrap import build_facade

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
# Integer-pixel boxes keep the element surface on the canvas pixel grid, so the two paths can be
# compared byte-for-byte rather than modulo resampling.
_TEXT = (
    "    - id: t\n      type: text\n      text: 'III'\n"
    "      style: {{font: Inter, font_size: 120px, font_weight: 900, color: '#FF0000', "
    "opacity: 0.5}}\n"
    "{effects}"
    "      constraints: {{anchor: {{top: parent.top+40px, left: parent.left+10px}}, "
    "size: {{w: 180px, h: 120px}}}}\n"
)
_NOOP_EFFECT = "      effects: [{name: blur, params: {radius: 0}}]\n"


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201
    return build_facade()


def _render(facade, tmp_path: Path, body: str) -> np.ndarray:  # noqa: ANN001
    tmp_path.mkdir(parents=True, exist_ok=True)
    template = tmp_path / "t.yaml"
    template.write_text(_HEAD + body, encoding="utf-8")
    out = tmp_path / "out.png"
    result = facade.render_file(template, format_name="sq", output=out)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    array: np.ndarray = skia.Image.open(str(out)).toarray(
        colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
    )
    return array


def _count(mask: np.ndarray) -> int:
    return int(np.count_nonzero(mask))


# ---------------------------------------------------------------------------------- text
def test_plain_text_honours_style_opacity(facade, tmp_path: Path) -> None:  # noqa: ANN001
    array = _render(facade, tmp_path, _TEXT.format(effects=""))
    r, g, b = (array[:, :, i].astype(int) for i in range(3))
    # No glyph pixel is pure ink; fully covered pixels blend halfway to the white ground.
    assert _count((r == 255) & (g == 0) & (b == 0)) == 0
    assert _count((r == 255) & (g >= 120) & (g <= 136) & (g == b)) > 500


def test_plain_text_opacity_matches_the_effects_path_byte_for_byte(
    facade, tmp_path: Path  # noqa: ANN001
) -> None:
    plain = _render(facade, tmp_path / "plain", _TEXT.format(effects=""))
    layered = _render(facade, tmp_path / "fx", _TEXT.format(effects=_NOOP_EFFECT))
    assert np.array_equal(plain, layered)


# --------------------------------------------------------------------------------- group
_GROUP = (
    "    - id: g\n      type: group\n      style: {{opacity: 0.5}}\n"
    "{effects}"
    "      constraints: {{anchor: {{top: parent.top, left: parent.left}}, "
    "size: {{w: fill, h: fill}}}}\n"
    "      children:\n"
    "        - id: r\n          type: shape\n          shape: rect\n"
    "          style: {{fill: '#FF0000'}}\n"
    "          constraints: {{anchor: {{top: parent.top+50px, left: parent.left+50px}}, "
    "size: {{w: 100px, h: 100px}}}}\n"
    "{second}"
)
# Substituted into _GROUP after formatting, so it carries plain braces.
_SECOND_CHILD = (
    "        - id: r2\n          type: shape\n          shape: rect\n"
    "          style: {fill: '#FF0000'}\n"
    "          constraints: {anchor: {top: parent.top+100px, left: parent.left+100px}, "
    "size: {w: 80px, h: 80px}}\n"
)


def test_group_opacity_composites_its_subtree(facade, tmp_path: Path) -> None:  # noqa: ANN001
    array = _render(facade, tmp_path, _GROUP.format(effects="", second=""))
    r, g, b, a = (int(v) for v in array[100, 100])
    assert r == 255 and 120 <= g <= 136 and g == b and a == 255, (r, g, b, a)


def test_plain_group_opacity_matches_the_effects_path_byte_for_byte(
    facade, tmp_path: Path  # noqa: ANN001
) -> None:
    plain = _render(facade, tmp_path / "plain", _GROUP.format(effects="", second=""))
    layered = _render(facade, tmp_path / "fx", _GROUP.format(effects=_NOOP_EFFECT, second=""))
    assert np.array_equal(plain, layered)


def test_group_opacity_fades_overlapping_children_as_one_layer(
    facade, tmp_path: Path  # noqa: ANN001
) -> None:
    """Where two opaque children overlap, the group's opacity applies once, not per child."""
    array = _render(facade, tmp_path, _GROUP.format(effects="", second=_SECOND_CHILD))
    alone = tuple(int(v) for v in array[75, 75])  # only the first child covers this pixel
    overlap = tuple(int(v) for v in array[125, 125])  # both children cover this pixel
    assert alone == overlap
    assert 120 <= alone[1] <= 136


def test_group_opacity_lives_in_style_not_on_the_node(tmp_path: Path) -> None:
    from arcavex.services.template.compiler import Compiler

    tmp_path.mkdir(parents=True, exist_ok=True)
    ok = tmp_path / "ok.yaml"
    ok.write_text(_HEAD + _GROUP.format(effects="", second=""), encoding="utf-8")
    result = Compiler().compile(ok, None, "sq", None, None)
    assert result.document is not None and not any(d.is_error() for d in result.diagnostics)
    assert result.document.root.children[1].style.opacity == 0.5

    bad = tmp_path / "bad.yaml"
    node_level = _GROUP.format(effects="", second="").replace(
        "style: {opacity: 0.5}", "opacity: 0.5"
    )
    bad.write_text(_HEAD + node_level, encoding="utf-8")
    result = Compiler().compile(bad, None, "sq", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-064")
    assert "style:" in (diag.hint or "")

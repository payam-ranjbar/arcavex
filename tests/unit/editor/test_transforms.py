"""Transform semantics: translation moves things, scale sizes them, one order everywhere.

Before this task the compiler parsed ``transform: {translate: ...}`` and the solver dropped it on
the floor: the value round-tripped through the IR and changed nothing. That is the worst kind of
wrong — a template author sees the field accepted and the poster unmoved. Scale was refused
outright.

The contract fixed here, shared by the solver, the backend, and everything that reads layout
geometry (selection bounds, hit testing, the Layers panel):

    local = translate ∘ rotate ∘ scale        (scale first, about the pivot; then rotation
                                               about the same pivot; then the offset)

with the pivot defaulting to the node's centre, exactly as rotation already behaved.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from arcavex.builtin.layout_anchors import AnchorLayoutSolver
from arcavex.kernel.contracts.types import MeasureRequest, MeasureResult
from arcavex.kernel.ir.models import (
    AnchorEdge,
    CanvasSpec,
    CompiledDocument,
    CompiledGroup,
    CompiledShape,
    Constraints,
    SizeSpec,
    Transform,
)

_SOLVER = AnchorLayoutSolver()


def _measure(request: MeasureRequest) -> MeasureResult:
    return MeasureResult(width_pt=10, height_pt=10, baseline_pt=8, line_count=1)


def _box(transform: Transform, size: float = 100.0) -> CompiledShape:
    return CompiledShape(
        id="box",
        transform=transform,
        constraints=Constraints(
            anchors={
                "left": AnchorEdge(ref="parent", edge="left", offset_pt=100.0),
                "top": AnchorEdge(ref="parent", edge="top", offset_pt=100.0),
            },
            width=SizeSpec(mode="fixed", value_pt=size),
            height=SizeSpec(mode="fixed", value_pt=size),
        ),
    )


def _solved(transform: Transform, size: float = 100.0):  # noqa: ANN202
    root = CompiledGroup(
        id="root",
        constraints=Constraints(
            anchors={"top": AnchorEdge(edge="top"), "left": AnchorEdge(edge="left")},
            width=SizeSpec(mode="fill"),
            height=SizeSpec(mode="fill"),
        ),
        children=(_box(transform, size),),
    )
    doc = CompiledDocument(canvas=CanvasSpec(width_pt=600, height_pt=600, dpi=72), root=root)
    return _SOLVER.solve(doc, _measure).root.children[0]


# ---------------------------------------------------------------------------------- translation


def test_translation_moves_the_painted_and_selectable_geometry() -> None:
    still = _solved(Transform())
    moved = _solved(Transform(translate=(40.0, -25.0)))

    assert moved.canvas_bounds is not None and still.canvas_bounds is not None
    assert moved.canvas_bounds.x == pytest.approx(still.canvas_bounds.x + 40.0)
    assert moved.canvas_bounds.y == pytest.approx(still.canvas_bounds.y - 25.0)
    assert moved.canvas_paint_bounds is not None and still.canvas_paint_bounds is not None
    assert moved.canvas_paint_bounds.x == pytest.approx(still.canvas_paint_bounds.x + 40.0)


def test_translation_does_not_move_the_anchor_box() -> None:
    """`bounds` stays where anchors placed it: siblings anchor to layout, transform is visual.

    This mirrors how rotation already behaves — anchoring against the post-transform AABB is
    the *paint* relationship, expressed through paint bounds, not a relocation of the box.
    """
    moved = _solved(Transform(translate=(40.0, -25.0)))

    assert moved.bounds.x == pytest.approx(100.0)
    assert moved.bounds.y == pytest.approx(100.0)


def test_the_absolute_transform_carries_the_translation_for_hit_testing() -> None:
    moved = _solved(Transform(translate=(40.0, -25.0)))

    x, y = moved.absolute_transform.apply(100.0, 100.0)
    assert (x, y) == (pytest.approx(140.0), pytest.approx(75.0))


# ---------------------------------------------------------------------------------------- scale


def test_scale_grows_the_painted_geometry_about_the_centre_by_default() -> None:
    doubled = _solved(Transform(scale=(2.0, 2.0)))

    assert doubled.canvas_paint_bounds is not None
    # A 100pt box at (100,100) scaled 2x about its centre (150,150) spans 50..250.
    assert doubled.canvas_paint_bounds.x == pytest.approx(50.0)
    assert doubled.canvas_paint_bounds.w == pytest.approx(200.0)


def test_scale_about_the_top_left_pivot_grows_away_from_it() -> None:
    scaled = _solved(Transform(scale=(2.0, 1.0), origin=(0.0, 0.0)))

    assert scaled.canvas_paint_bounds is not None
    assert scaled.canvas_paint_bounds.x == pytest.approx(100.0)
    assert scaled.canvas_paint_bounds.w == pytest.approx(200.0)
    assert scaled.canvas_paint_bounds.h == pytest.approx(100.0)


def test_translate_applies_after_scale_in_the_documented_order() -> None:
    combined = _solved(Transform(translate=(30.0, 0.0), scale=(2.0, 2.0), origin=(0.0, 0.0)))

    assert combined.canvas_paint_bounds is not None
    # Scale about (100,100) spans 100..300; the translation then shifts the whole span by 30.
    assert combined.canvas_paint_bounds.x == pytest.approx(130.0)
    assert combined.canvas_paint_bounds.w == pytest.approx(200.0)


def test_rotation_composes_with_scale_about_one_shared_pivot() -> None:
    node = _solved(Transform(rotate_deg=90.0, scale=(2.0, 1.0), origin=(0.0, 0.0)))

    assert node.canvas_paint_bounds is not None
    # Width scaled to 200 (span 100..300), then rotated +90° about (100,100). Positive degrees
    # rotate clockwise in the engine's y-down canvas space — matching how rotation has always
    # painted — so the scaled span swings downward: x 0..100, y 100..300.
    assert node.canvas_paint_bounds.w == pytest.approx(100.0)
    assert node.canvas_paint_bounds.h == pytest.approx(200.0)
    assert node.canvas_paint_bounds.x == pytest.approx(0.0)
    assert node.canvas_paint_bounds.y == pytest.approx(100.0)


# ---------------------------------------------------------------- compiler validation and pixels


def _render(template_text: str, tmp_path: Path) -> bytes:
    from arcavex.bootstrap import build_facade

    template = tmp_path / "template.yaml"
    template.write_text(template_text, encoding="utf-8")
    out = tmp_path / "out.png"
    facade = build_facade()
    result = facade.render_file(template, format_name="square", output=out)
    assert result.ok, result.diagnostics
    return out.read_bytes()


_TEMPLATE = """\
version: 0.1.0
formats:
  square: {{canvas: {{width: 200px, height: 200px, dpi: 72}}}}
preview_data: {{}}
root:
  type: group
  id: root
  children:
    - id: background
      type: shape
      shape: rect
      style: {{fill: "#000000"}}
      constraints:
        anchor: {{top: parent.top, left: parent.left}}
        size: {{w: fill, h: fill}}
    - id: box
      type: shape
      shape: rect
      style: {{fill: "#FFFFFF"}}
      {transform}
      constraints:
        anchor: {{top: parent.top+20px, left: parent.left+20px}}
        size: {{w: 40px, h: 40px}}
"""


def _pixel(png: bytes, x: int, y: int) -> tuple[int, int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        r, g, b = image.convert("RGB").getpixel((x, y))  # type: ignore[misc]
        return r, g, b


def test_a_translated_shape_actually_moves_in_the_rendered_pixels(tmp_path: Path) -> None:
    png = _render(
        _TEMPLATE.format(transform="transform: {translate: [100, 0]}"), tmp_path
    )

    assert _pixel(png, 40, 40) == (0, 0, 0), "the authored position must now be background"
    assert _pixel(png, 140, 40) == (255, 255, 255), "the shape must paint at its offset"


def test_a_scaled_shape_actually_grows_in_the_rendered_pixels(tmp_path: Path) -> None:
    png = _render(
        _TEMPLATE.format(transform="transform: {scale: 2, origin: top_left}"), tmp_path
    )

    # The 40px box at (20,20) scaled 2x about its top-left spans 20..100 in both axes.
    assert _pixel(png, 90, 90) == (255, 255, 255)
    assert _pixel(png, 110, 110) == (0, 0, 0)


def test_zero_and_negative_scale_are_rejected_at_compile_time(tmp_path: Path) -> None:
    from arcavex.bootstrap import build_facade

    facade = build_facade()
    for bad in ("0", "[-1, 1]"):
        template = tmp_path / "bad.yaml"
        template.write_text(
            _TEMPLATE.format(transform=f"transform: {{scale: {bad}}}"), encoding="utf-8"
        )
        result = facade.render_file(template, format_name="square", output=tmp_path / "bad.png")
        assert not result.ok
        assert any(diag.code == "ARC-IR-016" for diag in result.diagnostics), (
            bad,
            result.diagnostics,
        )


def test_scale_is_no_longer_refused_as_unsupported(tmp_path: Path) -> None:
    """ARC-RND-901 dies with this task: a uniform scale renders instead of erroring."""
    png = _render(_TEMPLATE.format(transform="transform: {scale: 1.5}"), tmp_path)

    assert png


def test_non_finite_scale_is_rejected(tmp_path: Path) -> None:
    from arcavex.bootstrap import build_facade

    facade = build_facade()
    template = tmp_path / "nan.yaml"
    template.write_text(
        _TEMPLATE.format(transform="transform: {scale: [.nan, 1]}"), encoding="utf-8"
    )
    result = facade.render_file(template, format_name="square", output=tmp_path / "nan.png")
    assert not result.ok
    assert any(diag.code in {"ARC-IR-014", "ARC-IR-016"} for diag in result.diagnostics)

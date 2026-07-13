"""Property-based tests for anchor resolution math (spec §8.5)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

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
)

_SOLVER = AnchorLayoutSolver()


def _measure(req: MeasureRequest) -> MeasureResult:
    return MeasureResult(width_pt=10, height_pt=10, baseline_pt=8, line_count=1)


def _fill() -> Constraints:
    return Constraints(
        anchors={"top": AnchorEdge(edge="top"), "left": AnchorEdge(edge="left")},
        width=SizeSpec(mode="fill"), height=SizeSpec(mode="fill"),
    )


def _solve(child: CompiledShape, direction: str = "ltr"):  # noqa: ANN202
    root = CompiledGroup(id="root", direction=direction, constraints=_fill(), children=(child,))
    doc = CompiledDocument(canvas=CanvasSpec(width_pt=1000, height_pt=1000, dpi=72), root=root)
    return _SOLVER.solve(doc, _measure).root.children[0]


_pt = st.floats(min_value=0.0, max_value=400.0, allow_nan=False, allow_infinity=False)
_size = st.floats(min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False)


@given(offset=_pt, width=_size, height=_size)
def test_left_anchor_offset_is_additive(offset: float, width: float, height: float) -> None:
    child = CompiledShape(
        id="box",
        constraints=Constraints(
            anchors={
                "left": AnchorEdge(ref="parent", edge="left", offset_pt=offset),
                "top": AnchorEdge(ref="parent", edge="top"),
            },
            width=SizeSpec(mode="fixed", value_pt=width),
            height=SizeSpec(mode="fixed", value_pt=height),
        ),
    )
    node = _solve(child)
    assert abs(node.bounds.x - offset) < 1e-2
    assert abs(node.bounds.w - width) < 1e-2


@given(offset=_pt, width=_size)
def test_logical_start_offset_flips_in_rtl(offset: float, width: float) -> None:
    """A logical 'start' offset moves inward: +x in ltr, -x from the right edge in rtl."""
    def child() -> CompiledShape:
        return CompiledShape(
            id="box",
            constraints=Constraints(
                anchors={
                    "start": AnchorEdge(ref="parent", edge="start", offset_pt=offset),
                    "top": AnchorEdge(ref="parent", edge="top"),
                },
                width=SizeSpec(mode="fixed", value_pt=width),
                height=SizeSpec(mode="fixed", value_pt=10.0),
            ),
        )

    ltr = _solve(child(), "ltr")
    assert abs(ltr.bounds.x - offset) < 1e-2
    rtl = _solve(child(), "rtl")
    # right edge sits 'offset' in from the canvas right edge (1000).
    assert abs(rtl.bounds.right - (1000.0 - offset)) < 1e-2


@given(w=_size, ar_w=st.integers(1, 20), ar_h=st.integers(1, 20))
def test_aspect_ratio_holds(w: float, ar_w: int, ar_h: int) -> None:
    child = CompiledShape(
        id="box",
        constraints=Constraints(
            anchors={"top": AnchorEdge(edge="top"), "left": AnchorEdge(edge="left")},
            width=SizeSpec(mode="fixed", value_pt=w),
            height=SizeSpec(mode="aspect", aspect_w=float(ar_h), aspect_h=float(ar_w)),
        ),
    )
    node = _solve(child)
    # h = w * (aspect_w/aspect_h) = w * ar_h/ar_w
    assert abs(node.bounds.h - w * ar_h / ar_w) < 1e-1

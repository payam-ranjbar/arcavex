"""Compiled and layout document models — the rendering contract.

Two distinct immutable states flow through the pipeline: a :class:`CompiledDocument`
(expressions resolved, units normalized to points, constraints still symbolic) produced by
the compiler, and a :class:`LayoutDocument` (every node given resolved bounds and an
absolute transform) produced by the layout solver. The renderer backend accepts only a
:class:`LayoutDocument`; layout never mutates a compiled document in place.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from arcavex.kernel.ir.units import Matrix3, Rect

RGBA = tuple[float, float, float, float]


# --------------------------------------------------------------------------- shared specs
class Transform(BaseModel):
    """A node transform in points and degrees, applied about ``origin``."""

    model_config = ConfigDict(frozen=True)

    translate: tuple[float, float] = (0.0, 0.0)
    rotate_deg: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)
    origin: tuple[float, float] | None = None  # relative 0..1 within node bounds

    @property
    def is_identity(self) -> bool:
        """Whether this transform is the identity."""
        return (
            self.translate == (0.0, 0.0)
            and self.rotate_deg == 0.0
            and self.scale == (1.0, 1.0)
        )


class AnchorEdge(BaseModel):
    """A resolved anchor: one edge of this node pinned to a reference edge.

    In Phase 0 the only reference is ``parent``. ``offset_pt`` is added after resolving the
    reference edge position.
    """

    model_config = ConfigDict(frozen=True)

    ref: Literal["parent"] = "parent"
    edge: Literal[
        "top", "bottom", "left", "right", "start", "end", "center_x", "center_y"
    ]
    offset_pt: float = 0.0


SizeMode = Literal["fixed", "percent", "fill", "fit_content"]


class SizeSpec(BaseModel):
    """A resolved size along one axis."""

    model_config = ConfigDict(frozen=True)

    mode: SizeMode
    value_pt: float | None = None  # for ``fixed``
    percent: float | None = None  # for ``percent`` (0..100)


class Constraints(BaseModel):
    """Positioning and sizing constraints for a node.

    ``anchors`` is keyed by the edge of *this* node being pinned (``top``, ``left``,
    ``right``, ``bottom``, ``center_x``, ``center_y``). Each node must resolve exactly one
    horizontal position, one vertical position, a width, and a height.
    """

    model_config = ConfigDict(frozen=True)

    anchors: dict[str, AnchorEdge] = Field(default_factory=dict)
    width: SizeSpec
    height: SizeSpec


class Style(BaseModel):
    """Visual style: fill/stroke for shapes and typography for text.

    Colors are stored as normalized straight-alpha RGBA tuples in ``[0, 1]``.
    """

    model_config = ConfigDict(frozen=True)

    # shape / fill
    fill: RGBA | None = None
    stroke: RGBA | None = None
    stroke_width_pt: float = 0.0
    corner_radius_pt: float = 0.0
    opacity: float = 1.0
    # text
    font_families: tuple[str, ...] = ()
    font_size_pt: float | None = None
    font_weight: int = 400
    italic: bool = False
    text_color: RGBA | None = None
    align: Literal["left", "right", "center", "start", "end"] = "start"
    direction: Literal["ltr", "rtl"] = "ltr"
    line_height: float | None = None
    letter_spacing_pt: float = 0.0


class EffectSpec(BaseModel):
    """A declared effect (contract-only in Phase 0; not executed)."""

    model_config = ConfigDict(frozen=True)

    name: str
    category: Literal["geometry", "color", "raster", "composite"]
    params: dict[str, object] = Field(default_factory=dict)


class MaskSpec(BaseModel):
    """A declared mask (contract-only in Phase 0; not executed)."""

    model_config = ConfigDict(frozen=True)

    component: str
    params: dict[str, object] = Field(default_factory=dict)


# ------------------------------------------------------------------------- compiled nodes
class _CompiledNodeBase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    transform: Transform = Transform()
    constraints: Constraints
    style: Style = Style()
    effects: tuple[EffectSpec, ...] = ()
    mask: MaskSpec | None = None
    visible: bool = True
    z: int = 0


class CompiledGroup(_CompiledNodeBase):
    """A container node establishing a direction and optional clip."""

    type: Literal["group"] = "group"
    direction: Literal["ltr", "rtl"] = "ltr"
    clip: bool = False
    children: tuple[CompiledNode, ...] = ()


class CompiledText(_CompiledNodeBase):
    """A text node holding a single resolved string."""

    type: Literal["text"] = "text"
    text: str


class CompiledImage(_CompiledNodeBase):
    """An image node. Phase 0 resolves a template-relative path directly."""

    type: Literal["image"] = "image"
    asset_path: str
    fit: Literal["fill", "contain", "cover"] = "cover"


class CompiledShape(_CompiledNodeBase):
    """A primitive shape node."""

    type: Literal["shape"] = "shape"
    shape: Literal["rect", "rrect", "circle"] = "rect"


class CompiledPath(_CompiledNodeBase):
    """A path node (minimal in Phase 0)."""

    type: Literal["path"] = "path"
    d: str = ""


CompiledNode = Annotated[
    CompiledGroup | CompiledText | CompiledImage | CompiledShape | CompiledPath,
    Field(discriminator="type"),
]


# ----------------------------------------------------------------------- compiled document
class CanvasSpec(BaseModel):
    """The resolved render canvas: extents in points plus device DPI."""

    model_config = ConfigDict(frozen=True)

    width_pt: float
    height_pt: float
    dpi: int
    bleed_pt: float = 0.0

    @property
    def width_px(self) -> int:
        """Canvas width in device pixels (rounded)."""
        return round(self.width_pt * self.dpi / 72.0)

    @property
    def height_px(self) -> int:
        """Canvas height in device pixels (rounded)."""
        return round(self.height_pt * self.dpi / 72.0)


class ColorPolicy(BaseModel):
    """Working color space policy (sRGB, premultiplied, sRGB blend for v1)."""

    model_config = ConfigDict(frozen=True)

    working_space: Literal["srgb"] = "srgb"
    premultiplied: bool = True
    blend_space: Literal["srgb"] = "srgb"


class FontRef(BaseModel):
    """A font family declared by the document, resolved from bundled fonts."""

    model_config = ConfigDict(frozen=True)

    family: str


class CompiledDocument(BaseModel):
    """A fully compiled, layout-independent scene document."""

    model_config = ConfigDict(frozen=True)

    ir_version: Literal["1.0"] = "1.0"
    canvas: CanvasSpec
    color_policy: ColorPolicy = ColorPolicy()
    seed: int = 0
    fonts: tuple[FontRef, ...] = ()
    root: CompiledGroup

    def canonical_dict(self) -> dict[str, object]:
        """Return a JSON-compatible dict for canonical hashing."""
        return self.model_dump(mode="json")


# -------------------------------------------------------------------------- layout results
class ResolvedText(BaseModel):
    """Resolved text content ready to shape and paint."""

    model_config = ConfigDict(frozen=True)

    text: str
    font_families: tuple[str, ...]
    font_size_pt: float
    font_weight: int
    italic: bool
    color: RGBA
    align: Literal["left", "right", "center", "start", "end"]
    direction: Literal["ltr", "rtl"]
    line_height: float | None
    letter_spacing_pt: float


class ResolvedImage(BaseModel):
    """Resolved image content."""

    model_config = ConfigDict(frozen=True)

    asset_path: str
    fit: Literal["fill", "contain", "cover"]


class ResolvedShape(BaseModel):
    """Resolved shape content."""

    model_config = ConfigDict(frozen=True)

    shape: Literal["rect", "rrect", "circle"]
    fill: RGBA | None
    stroke: RGBA | None
    stroke_width_pt: float
    corner_radius_pt: float


ResolvedContent = ResolvedText | ResolvedImage | ResolvedShape | None


class LayoutNode(BaseModel):
    """A node with resolved geometry in canvas point space."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    source_node_id: str
    kind: Literal["group", "text", "image", "shape", "path"]
    bounds: Rect
    absolute_transform: Matrix3
    paint_bounds: Rect
    overflow: Literal["none", "clip", "allow", "error"] = "none"
    opacity: float = 1.0
    visible: bool = True
    clip: bool = False
    resolved_content: ResolvedContent = None
    children: tuple[LayoutNode, ...] = ()


class ResolvedCanvas(BaseModel):
    """The canvas as seen by the renderer."""

    model_config = ConfigDict(frozen=True)

    width_pt: float
    height_pt: float
    dpi: int


class LayoutDocument(BaseModel):
    """A laid-out scene: every node has resolved bounds and absolute transform."""

    model_config = ConfigDict(frozen=True)

    canvas: ResolvedCanvas
    seed: int
    root: LayoutNode


CompiledGroup.model_rebuild()
LayoutNode.model_rebuild()

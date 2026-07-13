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

from arcavex.kernel.diagnostics import Diagnostic
from arcavex.kernel.ir.units import Matrix3, Rect

RGBA = tuple[float, float, float, float]


class SourceRef(BaseModel):
    """A node's authoring source location, carried for render/layout-time diagnostics.

    This is excluded from serialization (``exclude=True``) so it never enters the canonical
    hash — canonical forms must contain no absolute filesystem paths (spec §3.1.4) — while
    still letting the solver and backend cite the node's file/line/keypath (RR-3).
    """

    model_config = ConfigDict(frozen=True)

    file: str | None = None
    keypath: str | None = None
    line: int | None = None


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


EdgeName = Literal[
    "top", "bottom", "left", "right", "start", "end", "center_x", "center_y"
]


class AnchorEdge(BaseModel):
    """A resolved anchor: one edge of this node pinned to a reference edge.

    ``ref`` is ``"parent"`` or the resolved id of a sibling node. ``edge`` may be a physical
    edge or a logical ``start``/``end`` that the solver resolves through the enclosing group's
    direction. ``offset_pt`` is added after resolving the reference edge position.
    """

    model_config = ConfigDict(frozen=True)

    ref: str = "parent"
    edge: EdgeName
    offset_pt: float = 0.0


SizeMode = Literal["fixed", "percent", "fill", "fit_content", "aspect"]


class SizeSpec(BaseModel):
    """A resolved size along one axis.

    ``min_pt``/``max_pt`` clamp the resolved value on any mode. ``aspect`` derives this axis
    from the other axis using ``aspect_w``/``aspect_h`` (this-axis : other-axis ratio).
    """

    model_config = ConfigDict(frozen=True)

    mode: SizeMode
    value_pt: float | None = None  # for ``fixed``
    percent: float | None = None  # for ``percent`` (0..100)
    aspect_w: float | None = None  # for ``aspect``: numerator (this axis)
    aspect_h: float | None = None  # for ``aspect``: denominator (other axis)
    min_pt: float | None = None
    max_pt: float | None = None


StackLayout = Literal["absolute", "hstack", "vstack"]
MainAlign = Literal["start", "center", "end", "space_between"]
CrossAlign = Literal["start", "center", "end", "stretch"]


class StackSpec(BaseModel):
    """A group's stack layout: main-axis flow, gaps, padding, and alignment.

    ``kind == "absolute"`` means children position themselves with anchors (the Phase 0
    behavior). ``hstack``/``vstack`` flow children along the main axis with ``gap_pt`` between
    them, ``padding`` inside the group, ``main_align`` distributing free main-axis space, and
    ``cross_align`` placing/stretching each child on the cross axis.
    """

    model_config = ConfigDict(frozen=True)

    kind: StackLayout = "absolute"
    gap_pt: float = 0.0
    pad_top_pt: float = 0.0
    pad_right_pt: float = 0.0
    pad_bottom_pt: float = 0.0
    pad_left_pt: float = 0.0
    main_align: MainAlign = "start"
    cross_align: CrossAlign = "start"
    wrap: bool = False


class Constraints(BaseModel):
    """Positioning and sizing constraints for a node.

    ``anchors`` is keyed by the edge of *this* node being pinned (physical ``top``/``left``/…
    or logical ``start``/``end``). Outside a stack, each node must resolve exactly one
    horizontal position, one vertical position, a width, and a height. Inside a stack the main
    axis and cross-axis position come from the stack, so anchors are forbidden (a located
    error).
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
    language: str | None = None


class EffectSpec(BaseModel):
    """A declared effect (contract-only in Phase 0; not executed)."""

    model_config = ConfigDict(frozen=True)

    name: str
    category: Literal["geometry", "color", "raster", "composite"]
    params: dict[str, object] = Field(default_factory=dict)


class MaskSpec(BaseModel):
    """A declared mask resolved through the mask-generator registry at render time."""

    model_config = ConfigDict(frozen=True)

    component: str
    params: dict[str, object] = Field(default_factory=dict)


# --------------------------------------------------------------------------- text models
FitPolicy = Literal["wrap", "shrink_to_fit", "truncate"]
OverflowPolicy = Literal["clip", "allow", "error"]


class TextRun(BaseModel):
    """One run of text within a paragraph, with optional per-run typography overrides.

    A run inherits the node's :class:`Style` for any field left ``None``; per-run font
    families let a Latin span inside a Farsi paragraph shape with its own family while staying
    in one paragraph (SkParagraph fallback, spec §4.3).
    """

    model_config = ConfigDict(frozen=True)

    text: str
    font_families: tuple[str, ...] = ()
    font_size_pt: float | None = None
    font_weight: int | None = None
    italic: bool | None = None
    color: RGBA | None = None
    letter_spacing_pt: float | None = None


class ParagraphSpec(BaseModel):
    """Paragraph-level text layout: alignment and base direction."""

    model_config = ConfigDict(frozen=True)

    align: Literal["left", "right", "center", "start", "end"] = "start"
    direction: Literal["ltr", "rtl", "auto"] = "auto"


class FitSpec(BaseModel):
    """A text fit policy controlling how text is fitted into its resolved box.

    ``policy`` is ``wrap`` (default), ``shrink_to_fit`` (reduce size to ``min_size_pt``), or
    ``truncate`` (clip to an ellipsis). ``overflow`` decides what happens when text still does
    not fit: ``clip`` (hard clip), ``allow`` (paint beyond bounds), or ``error`` (fail).
    """

    model_config = ConfigDict(frozen=True)

    policy: FitPolicy = "wrap"
    min_size_pt: float | None = None
    overflow: OverflowPolicy = "clip"
    max_lines: int | None = None


OverflowKind = Literal["none", "clipped", "truncated", "shrunk", "overflowing"]


class OverflowState(BaseModel):
    """The recorded outcome of fitting text into a box (spec §4.2/§4.3).

    ``kind`` is the observed result; ``measured_w_pt``/``measured_h_pt`` are the shaped
    extents, and ``box_w_pt``/``box_h_pt`` are the target extents, so inspection can report by
    how much text over/underran.
    """

    model_config = ConfigDict(frozen=True)

    kind: OverflowKind = "none"
    measured_w_pt: float = 0.0
    measured_h_pt: float = 0.0
    box_w_pt: float = 0.0
    box_h_pt: float = 0.0
    resolved_size_pt: float | None = None  # the font size actually used after shrink_to_fit


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
    # Authoring location, kept out of serialization/hash but used for located diagnostics.
    source: SourceRef | None = Field(default=None, exclude=True)


class CompiledGroup(_CompiledNodeBase):
    """A container node establishing a direction, optional stack layout, and optional clip."""

    type: Literal["group"] = "group"
    direction: Literal["ltr", "rtl"] = "ltr"
    clip: bool = False
    stack: StackSpec = StackSpec()
    children: tuple[CompiledNode, ...] = ()


class CompiledText(_CompiledNodeBase):
    """A text node holding one or more runs plus paragraph and fit policy.

    ``runs`` is always populated (a plain ``text:`` compiles to a single run); ``text`` keeps
    the concatenated plain string for measurement fallbacks and inspection.
    """

    type: Literal["text"] = "text"
    text: str
    runs: tuple[TextRun, ...] = ()
    paragraph: ParagraphSpec = ParagraphSpec()
    fit: FitSpec = FitSpec()


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
class ResolvedRun(BaseModel):
    """One fully resolved text run ready to shape (every field concrete)."""

    model_config = ConfigDict(frozen=True)

    text: str
    font_families: tuple[str, ...]
    font_size_pt: float
    font_weight: int
    italic: bool
    color: RGBA
    letter_spacing_pt: float


class ResolvedText(BaseModel):
    """Resolved text content ready to shape and paint.

    ``font_size_pt`` is the *resolved* size after any ``shrink_to_fit`` pass; the runs carry
    the same size unless a run overrode it. ``clip`` tells the renderer to clip painting to the
    node bounds (``overflow: clip`` or ``truncate``).
    """

    model_config = ConfigDict(frozen=True)

    text: str
    runs: tuple[ResolvedRun, ...]
    font_families: tuple[str, ...]
    font_size_pt: float
    font_weight: int
    italic: bool
    color: RGBA
    align: Literal["left", "right", "center", "start", "end"]
    direction: Literal["ltr", "rtl"]
    line_height: float | None
    letter_spacing_pt: float
    language: str | None = None
    clip: bool = False


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
    overflow: OverflowState = OverflowState()
    rotate_deg: float = 0.0
    rotate_origin: tuple[float, float] | None = None  # absolute pt centre of rotation
    opacity: float = 1.0
    visible: bool = True
    clip: bool = False
    mask: MaskSpec | None = None
    resolved_content: ResolvedContent = None
    children: tuple[LayoutNode, ...] = ()
    # Authoring location propagated from the compiled node for located diagnostics (RR-3).
    source: SourceRef | None = Field(default=None, exclude=True)


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
    # Non-fatal diagnostics raised during layout (missing glyphs, fit non-convergence),
    # surfaced by the facade alongside compile diagnostics. Excluded from any hashing.
    warnings: tuple[Diagnostic, ...] = ()


CompiledGroup.model_rebuild()
LayoutNode.model_rebuild()

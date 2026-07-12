"""Shared value types used across the contract (SPI) surface.

These types describe what flows between the kernel and its implementations without pulling
any rendering backend into the kernel. Opaque handles (``Surface``, ``Path2D``,
``DecodedAsset``) are declared as structural protocols so the kernel need not import skia.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Literal, Protocol, Union, runtime_checkable

from pydantic import BaseModel, ConfigDict

# Values that may pass through the expression evaluator and template functions.
# Written with typing.Union rather than ``|`` because the recursive forward reference to
# ``Value`` inside a runtime ``X | Y`` expression is not evaluable at module import time.
Value = Union[str, int, float, bool, None, list["Value"], dict[str, "Value"]]  # noqa: UP007


class EffectKind(StrEnum):
    """The category of an effect, which determines its execution stage."""

    GEOMETRY = "geometry"
    COLOR = "color"
    RASTER = "raster"
    COMPOSITE = "composite"


@runtime_checkable
class Surface(Protocol):
    """An opaque rendered surface handle produced by a renderer backend."""


@runtime_checkable
class Path2D(Protocol):
    """An opaque 2D path handle produced by shape/mask generators."""


@runtime_checkable
class DecodedAsset(Protocol):
    """An opaque decoded asset handle produced by an asset decoder."""


class MeasureRequest(BaseModel):
    """A text measurement request passed to the measurement function."""

    model_config = ConfigDict(frozen=True)

    text: str
    font_families: tuple[str, ...]
    font_size_pt: float
    font_weight: int = 400
    italic: bool = False
    letter_spacing_pt: float = 0.0
    line_height: float | None = None
    direction: Literal["ltr", "rtl"] = "ltr"
    max_width_pt: float | None = None


class MeasureResult(BaseModel):
    """The result of measuring text: extents and baseline in points."""

    model_config = ConfigDict(frozen=True)

    width_pt: float
    height_pt: float
    baseline_pt: float
    line_count: int


MeasureFn = Callable[[MeasureRequest], MeasureResult]


class RenderOptions(BaseModel):
    """Options controlling a render pass."""

    model_config = ConfigDict(frozen=True)

    dpi: int | None = None
    debug: bool = False


class ExportOptions(BaseModel):
    """Options controlling an export."""

    model_config = ConfigDict(frozen=True)

    quality: int = 100
    dpi: int | None = None


class ExportReport(BaseModel):
    """The result of an export: the written path and its content hash."""

    model_config = ConfigDict(frozen=True)

    path: str
    format: str
    bytes_written: int
    content_sha256: str


class DecodeGuards(BaseModel):
    """Resource guards enforced by asset decoders before expensive decode."""

    model_config = ConfigDict(frozen=True)

    max_pixels: int = 100_000_000
    max_source_bytes: int = 64_000_000

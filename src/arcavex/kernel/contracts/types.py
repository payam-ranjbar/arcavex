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

from arcavex.kernel.ir.models import ResolvedRun

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
    """A text measurement / fit request passed to the measurement function.

    A simple request supplies ``text`` + ``font_families`` + ``font_size_pt`` (a single run is
    synthesized). A rich request supplies ``runs`` (each a fully resolved run) and leaves
    ``text`` as the concatenated plain string; when ``runs`` is non-empty it drives shaping.

    Fit fields (``fit_policy``/``min_size_pt``/``max_lines`` plus ``max_width_pt`` and
    ``max_height_pt``) let the text service run the ≤8-iteration fit loop (ADR-0001) and report
    the outcome, so the layout solver calls the shaper once per node.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    font_families: tuple[str, ...]
    font_size_pt: float
    font_weight: int = 400
    italic: bool = False
    letter_spacing_pt: float = 0.0
    line_height: float | None = None
    direction: Literal["ltr", "rtl"] = "ltr"
    align: Literal["left", "right", "center", "start", "end"] = "start"
    language: str | None = None
    color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    max_width_pt: float | None = None
    max_height_pt: float | None = None
    runs: tuple[ResolvedRun, ...] = ()
    fit_policy: Literal["wrap", "shrink_to_fit", "truncate"] = "wrap"
    min_size_pt: float | None = None
    max_lines: int | None = None


class MeasureResult(BaseModel):
    """The result of measuring/fitting text: extents, baseline, and the fit outcome.

    ``resolved_size_pt`` is the font size actually used (after ``shrink_to_fit``);
    ``overflow_kind`` classifies the outcome; ``out_text`` carries a truncated string when the
    ``truncate`` policy trimmed it; ``converged`` is ``False`` when the fit loop hit its
    iteration cap without settling.
    """

    model_config = ConfigDict(frozen=True)

    width_pt: float
    height_pt: float
    baseline_pt: float
    line_count: int
    resolved_size_pt: float = 0.0
    overflow_kind: Literal[
        "none", "clipped", "truncated", "shrunk", "overflowing"
    ] = "none"
    out_text: str | None = None
    converged: bool = True
    # (codepoint, families_tried) for glyphs no bundled font can render.
    missing_glyphs: tuple[tuple[int, tuple[str, ...]], ...] = ()


MeasureFn = Callable[[MeasureRequest], MeasureResult]


class RenderOptions(BaseModel):
    """Options controlling a render pass."""

    model_config = ConfigDict(frozen=True)

    dpi: int | None = None
    debug: bool = False
    # Debug hook: when set, the backend records each node's compiled effect plan (post-fusion)
    # so a test can assert that consecutive color effects actually collapsed (spec §4.4).
    collect_plan: bool = False


class ExportOptions(BaseModel):
    """Options controlling an export.

    ``quality`` is the lossy encoder quality (JPEG, lossy WebP), defaulting to 90 — the
    conventional "visually lossless, small" setting; ``lossless`` switches WebP to
    its lossless mode (encoded at quality 100). ``page_width_pt``/``page_height_pt`` carry the
    physical *trim* size and ``bleed_pt`` the uniform bleed margin for the PDF exporter, which
    needs the physical page geometry the raster surface alone cannot express (spec §4.6/§3.1.2);
    raster exporters ignore them. ``engine_version`` is embedded as stable PDF metadata (never a
    timestamp), so identical inputs stay byte-identical (spec §4.6).
    """

    model_config = ConfigDict(frozen=True)

    quality: int = 90
    dpi: int | None = None
    lossless: bool = False
    page_width_pt: float | None = None
    page_height_pt: float | None = None
    bleed_pt: float = 0.0
    engine_version: str = ""


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

"""The Arcavex extension SDK — the one public surface a trusted local extension imports.

An extension imports **only** ``arcavex.sdk`` (this package) plus the documented IR value types
re-exported here; it must not reach into ``arcavex.kernel`` internals, ``arcavex.services``,
``arcavex.builtin``, or ``arcavex.clients``. The extension validator enforces that surface as an
authoring/compatibility rule (spec §7.2) — it improves reliability, it is not a security sandbox:
a Python extension runs with the full permissions of the Arcavex process and is trusted local
code reviewed like any other dependency (spec §7.3).

What this module re-exports:

- **Contracts (SPI)** — the eight abstract bases a component subclasses: :class:`Effect`,
  :class:`MaskGenerator`, :class:`ShapeGenerator`, :class:`Exporter`, :class:`LayoutSolver`,
  :class:`TemplateFunction`, :class:`RendererBackend`, :class:`AssetDecoder`.
- **Effect contexts** — the per-category ``apply`` inputs: :class:`GeometryContext`,
  :class:`ColorContext`, :class:`RasterContext`, :class:`CompositeContext`.
- **Color transforms** a ``COLOR`` effect returns: :class:`ColorMatrix`, :class:`ColorTable`,
  and :func:`compose_color_matrices`.
- **Determinism** — :func:`effect_rng`, the single seeded-RNG-tree helper every effect draws
  randomness from (spec §3.2).
- **Path / surface utilities** — :class:`SurfacePool`, :func:`render_to_pool`,
  :func:`image_to_rgba`, :func:`rgba_to_image`.
- **Param-schema helpers** — the pydantic base (re-exported :class:`BaseModel`/:class:`Field`)
  plus the unit-aware fields :data:`Points` and :data:`RGBAColor`.
- **IR value types** — :class:`Rect`, :class:`Insets`, :class:`Dim`, :class:`Matrix3`,
  :class:`Unit`, :class:`Color`, and the :class:`Path2D` / :class:`Surface` handle protocols.
- **Registration helpers** — :data:`COMPONENT_KINDS` / :func:`register_component`.
- **Testing** — :class:`GoldenHarness` for golden + bounds-expansion-honesty fixtures.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Contracts (SPI) — the abstract bases a component implements.
from arcavex.kernel.contracts.spi import (
    AssetDecoder,
    Effect,
    Exporter,
    LayoutSolver,
    MaskGenerator,
    RendererBackend,
    ShapeGenerator,
    TemplateFunction,
)

# Shared contract value types the SPI signatures use.
from arcavex.kernel.contracts.types import (
    DecodedAsset,
    DecodeGuards,
    EffectKind,
    ExportOptions,
    ExportReport,
    MeasureFn,
    MeasureRequest,
    MeasureResult,
    Path2D,
    RenderOptions,
    Surface,
    Value,
)

# Documented IR value types an extension may build with.
from arcavex.kernel.ir.colors import Color
from arcavex.kernel.ir.units import Dim, Insets, Matrix3, Rect, Unit, mm_to_pt, pt_to_px, px_to_pt

# SDK runtime + tooling.
from arcavex.sdk.color import (
    IDENTITY_MATRIX,
    LUMA,
    ColorMatrix,
    ColorTable,
    ColorTransform,
    compose_color_matrices,
)
from arcavex.sdk.context import (
    ColorContext,
    CompositeContext,
    GeometryContext,
    RasterContext,
)
from arcavex.sdk.golden import BoundsHonesty, GoldenHarness, GoldenResult, load_png, save_png
from arcavex.sdk.params import RGBA, Points, RGBAColor
from arcavex.sdk.registration import (
    COMPONENT_KINDS,
    ComponentKind,
    component_kinds,
    register_component,
)
from arcavex.sdk.rng import effect_rng
from arcavex.sdk.surface import SurfacePool, image_to_rgba, render_to_pool, rgba_to_image

# The stable version of the SDK surface. Bumped when the re-exported surface changes in a way an
# extension can observe; distinct from the engine and IR versions an extension declares against.
SDK_VERSION = "1.0"

__all__ = [
    "COMPONENT_KINDS",
    "IDENTITY_MATRIX",
    "LUMA",
    "RGBA",
    "SDK_VERSION",
    "AssetDecoder",
    "BaseModel",
    "BoundsHonesty",
    "Color",
    "ColorContext",
    "ColorMatrix",
    "ColorTable",
    "ColorTransform",
    "CompositeContext",
    "ComponentKind",
    "ConfigDict",
    "DecodeGuards",
    "DecodedAsset",
    "Dim",
    "Effect",
    "EffectKind",
    "ExportOptions",
    "ExportReport",
    "Exporter",
    "Field",
    "GeometryContext",
    "GoldenHarness",
    "GoldenResult",
    "Insets",
    "LayoutSolver",
    "MaskGenerator",
    "load_png",
    "Matrix3",
    "MeasureFn",
    "MeasureRequest",
    "MeasureResult",
    "Path2D",
    "Points",
    "RGBAColor",
    "RasterContext",
    "Rect",
    "RenderOptions",
    "RendererBackend",
    "ShapeGenerator",
    "Surface",
    "SurfacePool",
    "TemplateFunction",
    "Unit",
    "Value",
    "compose_color_matrices",
    "component_kinds",
    "effect_rng",
    "image_to_rgba",
    "mm_to_pt",
    "pt_to_px",
    "px_to_pt",
    "register_component",
    "render_to_pool",
    "rgba_to_image",
    "save_png",
]

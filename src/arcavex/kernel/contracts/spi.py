"""The eight service provider interfaces (SPI) — one per axis of variation.

Contracts face downward toward implementations (built-ins and, later, trusted local
extensions). Each is a stable abstract base with typed class variables. In Phase 0 only
:class:`LayoutSolver`, :class:`RendererBackend`, :class:`Exporter`, and
:class:`TemplateFunction` have working implementations; the remaining contracts exist for
registry completeness and are implemented in later phases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from arcavex.kernel.contracts.types import (
    DecodedAsset,
    DecodeGuards,
    EffectKind,
    ExportOptions,
    ExportReport,
    MeasureFn,
    Path2D,
    RenderOptions,
    Surface,
    Value,
)
from arcavex.kernel.ir.models import CompiledDocument, LayoutDocument
from arcavex.kernel.ir.units import Insets, Rect


class Effect(ABC):
    """A visual effect. Declares one category and a typed parameter schema."""

    kind: ClassVar[EffectKind]
    param_schema: ClassVar[type[BaseModel]]

    @abstractmethod
    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Return the outward bounds expansion this effect requires (may be zero)."""

    @abstractmethod
    def apply(self, ctx: object) -> object:
        """Apply the effect given a category-specific context."""


class MaskGenerator(ABC):
    """Builds a clip path for a mask from typed parameters and node bounds."""

    name: ClassVar[str]
    param_schema: ClassVar[type[BaseModel]]

    @abstractmethod
    def build(self, params: BaseModel, bounds: Rect) -> Path2D:
        """Build the mask path within ``bounds``."""


class ShapeGenerator(ABC):
    """Builds a path for a parametric shape (starburst, speech bubble, …)."""

    name: ClassVar[str]
    param_schema: ClassVar[type[BaseModel]]

    @abstractmethod
    def build(self, params: BaseModel, bounds: Rect) -> Path2D:
        """Build the shape path within ``bounds``."""


class Exporter(ABC):
    """Writes a rendered surface to a target file in a specific format."""

    format: ClassVar[str]

    @abstractmethod
    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport:
        """Export ``surface`` to ``target`` and return a report."""


class LayoutSolver(ABC):
    """Resolves a compiled document into a laid-out document."""

    name: ClassVar[str]

    @abstractmethod
    def solve(self, doc: CompiledDocument, measure: MeasureFn) -> LayoutDocument:
        """Resolve geometry for every node, returning a new immutable document."""


class TemplateFunction(ABC):
    """A pure, deterministic function callable from template expressions."""

    name: ClassVar[str]

    @abstractmethod
    def call(self, *args: Value) -> Value:
        """Evaluate the function. Must have no I/O or side effects."""


class RendererBackend(ABC):
    """Renders a laid-out document into a surface. Accepts only LayoutDocument."""

    name: ClassVar[str]

    @abstractmethod
    def render(self, doc: LayoutDocument, opts: RenderOptions) -> Surface:
        """Render ``doc`` and return the resulting surface."""


class AssetDecoder(ABC):
    """Decodes raw asset bytes into a usable asset, enforcing decode guards."""

    media_types: ClassVar[tuple[str, ...]]

    @abstractmethod
    def decode(self, blob: bytes, guards: DecodeGuards) -> DecodedAsset:
        """Decode ``blob`` under ``guards`` and return the decoded asset."""

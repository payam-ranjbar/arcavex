"""Typed component registries and their container.

One registry exists per contract. Registration is name-unique: a duplicate name raises a
:class:`DiagnosticError` naming both providers at bootstrap time (spec §3.3). Iteration
order is stable (sorted by name) to preserve determinism.
"""

from __future__ import annotations

from typing import Generic, TypeVar

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
from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic

T = TypeVar("T")


class Registry(Generic[T]):
    """A name-keyed registry for a single contract kind."""

    def __init__(self, kind: str) -> None:
        """Initialize an empty registry.

        Args:
            kind: A human-readable kind label used in diagnostics (e.g. ``"layout"``).
        """
        self._kind = kind
        self._items: dict[str, T] = {}

    def register(self, name: str, provider: T) -> None:
        """Register ``provider`` under ``name``.

        Raises:
            DiagnosticError: If ``name`` is already registered, naming both providers.
        """
        if name in self._items:
            existing = type(self._items[name]).__name__
            incoming = type(provider).__name__
            raise DiagnosticError(
                diagnostic(
                    "ARC-EXT-001",
                    f"Duplicate {self._kind} component name {name!r}: "
                    f"already provided by {existing}, cannot also register {incoming}",
                    hint="Component names are globally unique per kind. Rename one provider.",
                )
            )
        self._items[name] = provider

    def get(self, name: str) -> T:
        """Return the provider registered under ``name``.

        Raises:
            DiagnosticError: If no provider is registered under ``name``.
        """
        if name not in self._items:
            raise DiagnosticError(self.missing_diagnostic(name))
        return self._items[name]

    def missing_diagnostic(self, name: str) -> Diagnostic:
        """Return the diagnostic for a missing ``name`` in this registry."""
        available = ", ".join(self.names()) or "(none)"
        return diagnostic(
            "ARC-EXT-002",
            f"No {self._kind} component named {name!r} is registered",
            hint=f"Available {self._kind} components: {available}",
        )

    def has(self, name: str) -> bool:
        """Whether a provider is registered under ``name``."""
        return name in self._items

    def names(self) -> list[str]:
        """Return registered names in stable sorted order."""
        return sorted(self._items)


class Registries:
    """The container holding one registry per contract."""

    def __init__(self) -> None:
        """Create empty registries for every contract kind."""
        self.effects: Registry[Effect] = Registry("effect")
        self.masks: Registry[MaskGenerator] = Registry("mask")
        self.shapes: Registry[ShapeGenerator] = Registry("shape")
        self.exporters: Registry[Exporter] = Registry("exporter")
        self.layouts: Registry[LayoutSolver] = Registry("layout")
        self.template_fns: Registry[TemplateFunction] = Registry("template_fn")
        self.backends: Registry[RendererBackend] = Registry("backend")
        self.decoders: Registry[AssetDecoder] = Registry("decoder")


__all__ = ["Registries", "Registry"]

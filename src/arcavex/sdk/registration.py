"""Registration helpers: the component-kind table and a register-into-registries helper.

An extension does not self-register; its ``extension.toml`` declares components and the loader
registers each into the same typed registries the built-ins use, so a loaded component is
indistinguishable from a built-in at the pipeline (spec §3.3). This module is the single source
of truth for what the eight component kinds are — their manifest keyword, the contract they must
implement, which registry they land in, and the class attribute (if any) that must echo the
declared name. The loader, the validator, and a local golden test all read it, so they cannot
disagree about the set of kinds.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from arcavex.kernel.registry import Registries


@dataclass(frozen=True)
class ComponentKind:
    """One extensible component kind: its manifest keyword, contract, and registry slot.

    ``name_attr`` is the class variable a component of this kind must set to a string that echoes
    its declared name (``name`` for most, ``format`` for exporters); ``None`` means the kind is
    named only by the manifest (effects carry no name attribute — they are keyed by the authored
    name the manifest supplies).
    """

    keyword: str
    contract: type
    registry_attr: str
    name_attr: str | None


COMPONENT_KINDS: dict[str, ComponentKind] = {
    "effect": ComponentKind("effect", Effect, "effects", None),
    "mask": ComponentKind("mask", MaskGenerator, "masks", "name"),
    "shape": ComponentKind("shape", ShapeGenerator, "shapes", "name"),
    "exporter": ComponentKind("exporter", Exporter, "exporters", "format"),
    "layout_solver": ComponentKind("layout_solver", LayoutSolver, "layouts", "name"),
    "template_function": ComponentKind(
        "template_function", TemplateFunction, "template_fns", "name"
    ),
    "backend": ComponentKind("backend", RendererBackend, "backends", "name"),
    "decoder": ComponentKind("decoder", AssetDecoder, "decoders", None),
}


def component_kinds() -> tuple[str, ...]:
    """Return the manifest keywords for every supported component kind, in a stable order."""
    return tuple(COMPONENT_KINDS)


def register_component(
    registries: Registries, kind: str, name: str, provider: object
) -> None:
    """Register ``provider`` under ``name`` in the registry for ``kind``.

    Raises the same ``ARC-EXT-001`` duplicate-name diagnostic the built-in registration path
    raises, because it goes through the exact same registry (spec §3.3). ``kind`` must be a known
    component keyword.
    """
    spec = COMPONENT_KINDS[kind]
    registry = getattr(registries, spec.registry_attr)
    registry.register(name, provider)


__all__ = [
    "COMPONENT_KINDS",
    "ComponentKind",
    "component_kinds",
    "register_component",
]

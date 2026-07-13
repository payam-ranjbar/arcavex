"""Built-in mask generators (spec §3.2 MaskGenerator, §4.5).

Masks resolve through the ``MaskGenerator`` registry to a clip path applied to a node's
content (and its children, for a group). This package provides the v1 built-ins:
``rounded_rect``, ``circle``, and ``diamond_grid`` (the reference-poster photo treatment — a
lattice of rotated squares with the gutters left as gaps). Each declares a typed pydantic
parameter schema so invalid params fail at compile time with a located diagnostic.
"""

from __future__ import annotations

from arcavex.builtin.masks_core.masks import (
    CircleMask,
    DiamondGridMask,
    RoundedRectMask,
    builtin_masks,
)

__all__ = ["CircleMask", "DiamondGridMask", "RoundedRectMask", "builtin_masks"]

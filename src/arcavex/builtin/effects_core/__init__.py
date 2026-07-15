"""Built-in effect implementations and their registration list.

The renderer resolves effects only through the registry (spec §4.4); this package supplies the
v1 built-ins across the four categories. ``builtin_effects()`` returns them keyed by their
authored name for :mod:`arcavex.bootstrap` to register.
"""

from __future__ import annotations

from arcavex.builtin.effects_core.color import Duotone, Grade, Posterize, Threshold
from arcavex.builtin.effects_core.composite import DropShadow, Glow
from arcavex.builtin.effects_core.geometry import TornPaper
from arcavex.builtin.effects_core.raster import (
    Blur,
    ChannelOffset,
    EdgeWear,
    Grain,
    Halftone,
    InkBleed,
    Noise,
    PaletteMap,
)
from arcavex.kernel.contracts.spi import Effect

# Authored effect name -> implementation. Names are the stable authoring vocabulary.
_EFFECTS: dict[str, Effect] = {
    "blur": Blur(),
    "grain": Grain(),
    "noise": Noise(),
    "ink-bleed": InkBleed(),
    "halftone": Halftone(),
    "channel-offset": ChannelOffset(),
    "edge-wear": EdgeWear(),
    "palette-map": PaletteMap(),
    "duotone": Duotone(),
    "threshold": Threshold(),
    "grade": Grade(),
    "posterize": Posterize(),
    "drop-shadow": DropShadow(),
    "glow": Glow(),
    "torn-paper": TornPaper(),
}


def builtin_effects() -> dict[str, Effect]:
    """Return the built-in effects keyed by authored name."""
    return dict(_EFFECTS)


__all__ = ["builtin_effects"]

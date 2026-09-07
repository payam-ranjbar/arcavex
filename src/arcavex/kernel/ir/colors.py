"""Color parsing and normalization.

Colors are authored as hex (``#RGB`` / ``#RRGGBB`` / ``#RRGGBBAA``), ``rgb()`` /
``rgba()`` functional notation, or a small set of named CSS basic colors. ``transparent``
and its CSS/SVG-style alias ``none`` both mean "no paint" (fully transparent black), so a
stroke-only shape is written ``fill: none``. They are stored as normalized straight-alpha
RGBA floats in the range ``[0, 1]``. Premultiplication and blend-space handling are the
renderer's responsibility per the document color policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# CSS basic/extended subset sufficient for Phase 0 authoring.
_NAMED: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "lime": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "aqua": (0, 255, 255),
    "magenta": (255, 0, 255),
    "fuchsia": (255, 0, 255),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "maroon": (128, 0, 0),
    "olive": (128, 128, 0),
    "navy": (0, 0, 128),
    "teal": (0, 128, 128),
    "purple": (128, 0, 128),
    "orange": (255, 165, 0),
    "transparent": (0, 0, 0),
    # 'none' is how CSS and SVG spell "no paint"; authors reach for it before 'transparent',
    # and refusing it read as "a shape must always be filled".
    "none": (0, 0, 0),
}
_NAMED_ALPHA: dict[str, float] = {"transparent": 0.0, "none": 0.0}

_RGB_FUNC_RE = re.compile(
    r"^\s*rgba?\(\s*([^,]+),\s*([^,]+),\s*([^,]+?)\s*(?:,\s*([^,]+?)\s*)?\)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Color:
    """A normalized straight-alpha RGBA color with components in ``[0, 1]``."""

    r: float
    g: float
    b: float
    a: float = 1.0

    @classmethod
    def parse(cls, raw: str) -> Color:
        """Parse a color from hex, ``rgb()``/``rgba()``, a named color, or ``none``.

        Args:
            raw: The authored color string.

        Returns:
            The normalized :class:`Color`.

        Raises:
            ValueError: If the string is not a recognized color.
        """
        text = raw.strip()
        if text.startswith("#"):
            return cls._parse_hex(text)
        if text.lower().startswith("rgb"):
            return cls._parse_func(text)
        key = text.lower()
        if key in _NAMED:
            r, g, b = _NAMED[key]
            return cls(r / 255.0, g / 255.0, b / 255.0, _NAMED_ALPHA.get(key, 1.0))
        raise ValueError(f"invalid color: {raw!r}")

    @classmethod
    def _parse_hex(cls, text: str) -> Color:
        body = text[1:]
        if not re.fullmatch(r"[0-9a-fA-F]+", body):
            raise ValueError(f"invalid hex color: {text!r}")
        if len(body) == 3:
            r, g, b = (int(ch * 2, 16) for ch in body)
            return cls(r / 255.0, g / 255.0, b / 255.0, 1.0)
        if len(body) == 4:
            r, g, b, a = (int(ch * 2, 16) for ch in body)
            return cls(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        if len(body) == 6:
            r = int(body[0:2], 16)
            g = int(body[2:4], 16)
            b = int(body[4:6], 16)
            return cls(r / 255.0, g / 255.0, b / 255.0, 1.0)
        if len(body) == 8:
            r = int(body[0:2], 16)
            g = int(body[2:4], 16)
            b = int(body[4:6], 16)
            a = int(body[6:8], 16)
            return cls(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        raise ValueError(f"invalid hex color length: {text!r}")

    @classmethod
    def _parse_func(cls, text: str) -> Color:
        match = _RGB_FUNC_RE.match(text)
        if match is None:
            raise ValueError(f"invalid rgb()/rgba() color: {text!r}")
        r = _channel(match.group(1))
        g = _channel(match.group(2))
        b = _channel(match.group(3))
        alpha_raw = match.group(4)
        a = 1.0 if alpha_raw is None else _alpha(alpha_raw)
        return cls(r, g, b, a)

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Return the RGBA components as a tuple in ``[0, 1]``."""
        return (self.r, self.g, self.b, self.a)

    def canonical(self) -> str:
        """Return a stable canonical string form (``rgba(r,g,b,a)`` in [0,1])."""
        from arcavex.kernel.ir.units import _norm_float

        return (
            f"rgba({_norm_float(self.r)},{_norm_float(self.g)},"
            f"{_norm_float(self.b)},{_norm_float(self.a)})"
        )


def _channel(token: str) -> float:
    token = token.strip()
    if token.endswith("%"):
        pct = float(token[:-1])
        if not 0.0 <= pct <= 100.0:
            raise ValueError(f"rgb() percentage out of range: {token!r}")
        return pct / 100.0
    value = float(token)
    if not 0.0 <= value <= 255.0:
        raise ValueError(f"rgb() channel out of range 0-255: {token!r}")
    return value / 255.0


def _alpha(token: str) -> float:
    token = token.strip()
    if token.endswith("%"):
        pct = float(token[:-1])
        if not 0.0 <= pct <= 100.0:
            raise ValueError(f"rgba() alpha percentage out of range: {token!r}")
        return pct / 100.0
    value = float(token)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"rgba() alpha out of range 0-1: {token!r}")
    return value

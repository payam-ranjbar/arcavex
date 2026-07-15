"""Parametric shape generators: starburst, speech-bubble, and QR code.

Each :class:`~arcavex.kernel.contracts.spi.ShapeGenerator` builds a Skia path within the
node's point-space bounds; the renderer fills/strokes it like any shape. Generation is pure and
deterministic — the QR generator uses ``segno`` (pure-Python), so the same data always yields
the same modules and therefore byte-identical renders (spec §3.2).
"""

from __future__ import annotations

import math
from typing import Annotated, ClassVar

import segno
import skia  # type: ignore[import-untyped]
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from arcavex.kernel.contracts.spi import ShapeGenerator
from arcavex.kernel.ir.units import Dim, Rect


def _as_pt(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("expected a length, got a boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        dim = Dim.parse(value)
        if dim.unit.value in {"px", "%"}:
            raise ValueError(f"shape lengths must be pt or mm, not {dim.unit.value!r}")
        return dim.to_pt(72.0)
    raise ValueError(f"invalid length {value!r}")


Points = Annotated[float, BeforeValidator(_as_pt)]


# ------------------------------------------------------------------------------- starburst
class StarburstParams(BaseModel):
    """An N-pointed star: ``points`` spikes, inner vertices at ``inner_ratio`` of the radius."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    points: int = Field(default=12, ge=3, le=120)
    inner_ratio: float = Field(default=0.5, gt=0.0, lt=1.0)


class Starburst(ShapeGenerator):
    """A star/burst polygon inscribed in the node bounds."""

    name: ClassVar[str] = "starburst"
    param_schema: ClassVar[type[BaseModel]] = StarburstParams

    def build(self, params: BaseModel, bounds: Rect) -> skia.Path:
        """Build the starburst path centred in ``bounds``."""
        assert isinstance(params, StarburstParams)
        cx, cy = bounds.center_x, bounds.center_y
        outer = min(bounds.w, bounds.h) / 2.0
        inner = outer * params.inner_ratio
        path = skia.Path()
        n = params.points * 2
        for i in range(n):
            angle = -math.pi / 2.0 + i * math.pi / params.points
            radius = outer if i % 2 == 0 else inner
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.close()
        return path


# --------------------------------------------------------------------------- speech-bubble
class SpeechBubbleParams(BaseModel):
    """A rounded rectangle with a triangular tail on one ``side`` at ``position`` (0..1).

    ``corner`` is the corner radius; ``tail_width``/``tail_height`` size the tail. The tail
    grows outward from the chosen side, so it lives inside the node's declared bounds only when
    the author leaves room — otherwise it clips like any overflowing content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    corner: Points = Field(default=16.0, ge=0.0)
    side: str = Field(default="bottom")
    position: float = Field(default=0.5, ge=0.0, le=1.0)
    tail_width: Points = Field(default=24.0, gt=0.0)
    tail_height: Points = Field(default=20.0, gt=0.0)

    def model_post_init(self, _context: object) -> None:
        if self.side not in {"bottom", "top", "left", "right"}:
            raise ValueError("side must be one of: bottom, top, left, right")


class SpeechBubble(ShapeGenerator):
    """A speech-bubble path: rounded body plus a tail on one side."""

    name: ClassVar[str] = "speech_bubble"
    param_schema: ClassVar[type[BaseModel]] = SpeechBubbleParams

    def build(self, params: BaseModel, bounds: Rect) -> skia.Path:
        """Build the bubble path within ``bounds`` (body inset to leave room for the tail)."""
        assert isinstance(params, SpeechBubbleParams)
        th = params.tail_height
        # Inset the rounded body away from the tail side so the tail stays within bounds.
        insets = {
            "bottom": (0.0, 0.0, th, 0.0),
            "top": (th, 0.0, 0.0, 0.0),
            "left": (0.0, 0.0, 0.0, th),
            "right": (0.0, th, 0.0, 0.0),
        }[params.side]
        bx = bounds.x + insets[3]
        by = bounds.y + insets[0]
        bw = bounds.w - insets[1] - insets[3]
        bh = bounds.h - insets[0] - insets[2]
        radius = min(params.corner, bw / 2.0, bh / 2.0)
        body = skia.Path()
        body.addRoundRect(skia.Rect.MakeXYWH(bx, by, bw, bh), radius, radius)
        tail = _tail_path(params, Rect(bx, by, bw, bh), th)
        body.addPath(tail)
        return body


def _tail_path(params: SpeechBubbleParams, body: Rect, th: float) -> skia.Path:
    tw = params.tail_width
    tail = skia.Path()
    if params.side in {"bottom", "top"}:
        cx = body.x + params.position * body.w
        if params.side == "bottom":
            tail.moveTo(cx - tw / 2.0, body.bottom - 1.0)
            tail.lineTo(cx + tw / 2.0, body.bottom - 1.0)
            tail.lineTo(cx, body.bottom + th)
        else:
            tail.moveTo(cx - tw / 2.0, body.y + 1.0)
            tail.lineTo(cx + tw / 2.0, body.y + 1.0)
            tail.lineTo(cx, body.y - th)
    else:
        cy = body.y + params.position * body.h
        if params.side == "right":
            tail.moveTo(body.right - 1.0, cy - tw / 2.0)
            tail.lineTo(body.right - 1.0, cy + tw / 2.0)
            tail.lineTo(body.right + th, cy)
        else:
            tail.moveTo(body.x + 1.0, cy - tw / 2.0)
            tail.lineTo(body.x + 1.0, cy + tw / 2.0)
            tail.lineTo(body.x - th, cy)
    tail.close()
    return tail


# ---------------------------------------------------------------------------------- qr code
class QrCodeParams(BaseModel):
    """A QR code of ``data`` with a ``quiet_zone`` (module border) around it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data: str = Field(min_length=1)
    quiet_zone: int = Field(default=2, ge=0, le=8)


class QrCode(ShapeGenerator):
    """A QR-code path (one filled square per dark module), scaled square within bounds."""

    name: ClassVar[str] = "qr_code"
    param_schema: ClassVar[type[BaseModel]] = QrCodeParams

    def build(self, params: BaseModel, bounds: Rect) -> skia.Path:
        """Build the QR path centred and scaled to fit ``bounds`` (largest square that fits)."""
        assert isinstance(params, QrCodeParams)
        qr = segno.make(params.data, error="m")
        rows = list(qr.matrix_iter(scale=1, border=params.quiet_zone))
        count = len(rows)
        side = min(bounds.w, bounds.h)
        module = side / count
        ox = bounds.x + (bounds.w - side) / 2.0
        oy = bounds.y + (bounds.h - side) / 2.0
        path = skia.Path()
        for r, row in enumerate(rows):
            for c, dark in enumerate(row):
                if dark:
                    path.addRect(
                        skia.Rect.MakeXYWH(
                            ox + c * module, oy + r * module, module, module
                        )
                    )
        return path


def builtin_shapes() -> list[ShapeGenerator]:
    """Return the built-in shape generators for registration."""
    return [Starburst(), SpeechBubble(), QrCode()]

"""Geometry-category effect: torn-paper.

A geometry effect runs pre-raster and rewrites the node's path (spec §3.2), so it applies only
to nodes that expose one — shape and path nodes. The renderer enforces that at compile time;
applying torn-paper to text or an image is a located validation error. Torn-paper roughens the
node's rectangular outline with seeded perpendicular jitter, giving a hand-ripped edge; the
displacement is bounded by ``amplitude``, which is exactly what it declares as bounds growth.
"""

from __future__ import annotations

from typing import ClassVar

import skia  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from arcavex.builtin.effects_core.context import GeometryContext
from arcavex.builtin.effects_core.params import Points
from arcavex.kernel.contracts.spi import Effect
from arcavex.kernel.contracts.types import EffectKind
from arcavex.kernel.ir.units import Insets


class TornPaperParams(BaseModel):
    """Ripped-edge roughness: ``amplitude`` max jitter, ``segment`` spacing between tears."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amplitude: Points = Field(default=4.0, ge=0.0)
    segment: Points = Field(default=10.0, gt=0.0)


class TornPaper(Effect):
    """Roughen a shape/path node's bounding outline into a torn-paper edge."""

    kind: ClassVar[EffectKind] = EffectKind.GEOMETRY
    param_schema: ClassVar[type[BaseModel]] = TornPaperParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Tears push outward by at most ``amplitude`` on every side."""
        assert isinstance(params, TornPaperParams)
        a = params.amplitude
        return Insets(a, a, a, a)

    def apply(self, ctx: object) -> skia.Path:
        """Return a torn polygon tracing the node's bounding rectangle with seeded jitter."""
        assert isinstance(ctx, GeometryContext)
        p = ctx.params
        assert isinstance(p, TornPaperParams)
        b = ctx.bounds
        amp, seg = p.amplitude, p.segment
        rng = ctx.rng
        # Walk the four edges clockwise; each interior vertex gets a jitter perpendicular to its
        # edge (outward-positive), so the ripped contour still encloses the node's corners.
        pts: list[tuple[float, float]] = []
        edges = (
            ((b.x, b.y), (b.right, b.y), (0.0, -1.0)),       # top,    normal up
            ((b.right, b.y), (b.right, b.bottom), (1.0, 0.0)),  # right,  normal right
            ((b.right, b.bottom), (b.x, b.bottom), (0.0, 1.0)),  # bottom, normal down
            ((b.x, b.bottom), (b.x, b.y), (-1.0, 0.0)),      # left,   normal left
        )
        for (x0, y0), (x1, y1), (nx, ny) in edges:
            length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            steps = max(1, int(length / seg))
            for i in range(steps):
                t = i / steps
                px = x0 + (x1 - x0) * t
                py = y0 + (y1 - y0) * t
                jitter = float(rng.uniform(-amp, amp)) if i > 0 else 0.0
                pts.append((px + nx * jitter, py + ny * jitter))
        path = skia.Path()
        path.moveTo(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.close()
        return path

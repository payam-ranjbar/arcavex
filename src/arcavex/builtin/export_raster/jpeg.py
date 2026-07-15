"""JPEG exporter.

Encodes a Skia surface to a baseline JPEG at ``ExportOptions.quality`` and writes it atomically.
JPEG has no alpha channel, so the render is first flattened over opaque white — done explicitly
so the result is deterministic rather than depending on the encoder's undefined treatment of a
premultiplied backdrop. Skia's JPEG encoder is deterministic, so identical inputs produce
byte-identical files (spec §4.6).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.builtin.export_raster import encode as _enc
from arcavex.kernel.contracts.spi import Exporter
from arcavex.kernel.contracts.types import ExportOptions, ExportReport, Surface

_WHITE = skia.Color4f(1.0, 1.0, 1.0, 1.0)


class JpegExporter(Exporter):
    """Exports a rendered surface as a baseline JPEG file."""

    format: ClassVar[str] = "jpeg"

    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport:
        """Encode ``surface`` to JPEG at ``target`` and return a report."""
        image = _enc.flatten_over(_enc.snapshot(surface), _WHITE)
        quality = _clamp_quality(opts.quality)
        payload = _enc.encode(image, skia.EncodedImageFormat.kJPEG, quality, "jpeg")
        return _enc.write_report(payload, target, "jpeg")


def _clamp_quality(quality: int) -> int:
    """Clamp an authored quality into the encoder's valid 1..100 range."""
    return max(1, min(100, quality))

"""PNG exporter.

Encodes a Skia surface to lossless PNG and writes it atomically. The encoded bytes carry no
timestamps or run metadata, so identical inputs produce byte-identical files (spec §4.6). The
content hash is reported for provenance. Encoding and the atomic write are shared with the JPEG
and WebP exporters via :mod:`arcavex.builtin.export_raster.encode`.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.builtin.export_raster import encode as _enc
from arcavex.kernel.contracts.spi import Exporter
from arcavex.kernel.contracts.types import ExportOptions, ExportReport, Surface


class PngExporter(Exporter):
    """Exports a rendered surface as a lossless PNG file."""

    format: ClassVar[str] = "png"

    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport:
        """Encode ``surface`` to PNG at ``target`` and return a report."""
        image = _enc.snapshot(surface)
        # PNG is lossless; Skia ignores the quality argument for it, so a fixed value keeps the
        # call shape uniform with the lossy encoders.
        payload = _enc.encode(image, skia.EncodedImageFormat.kPNG, 100, "png")
        return _enc.write_report(payload, target, "png")

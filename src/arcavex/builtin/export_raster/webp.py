"""WebP exporter.

Encodes a Skia surface to WebP and writes it atomically. WebP keeps the alpha channel, so no
flattening is needed. ``ExportOptions.lossless`` selects Skia's lossless WebP path (VP8L), which
the binding reaches by encoding at quality 100 — a round-trip through that path is bit-exact, so
``lossless`` is honoured, not approximated; otherwise a lossy VP8 image is written at the
requested ``quality``. Skia's WebP encoder is deterministic, so identical inputs produce
byte-identical files (spec §4.6).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.builtin.export_raster import encode as _enc
from arcavex.kernel.contracts.spi import Exporter
from arcavex.kernel.contracts.types import ExportOptions, ExportReport, Surface


class WebpExporter(Exporter):
    """Exports a rendered surface as a WebP file (lossy or lossless)."""

    format: ClassVar[str] = "webp"

    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport:
        """Encode ``surface`` to WebP at ``target`` and return a report."""
        image = _enc.snapshot(surface)
        # Skia's WebP encoder switches to lossless VP8L at quality 100; any lower value is lossy.
        quality = 100 if opts.lossless else max(1, min(99, opts.quality))
        payload = _enc.encode(image, skia.EncodedImageFormat.kWEBP, quality, "webp")
        return _enc.write_report(payload, target, "webp")

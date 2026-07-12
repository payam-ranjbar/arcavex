"""PNG exporter.

Encodes a Skia surface to PNG and writes it atomically (temporary file then rename). The
encoded bytes carry no timestamps or run metadata, so identical inputs produce byte-identical
files (spec §4.6). The content hash is reported for provenance.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.kernel.contracts.spi import Exporter
from arcavex.kernel.contracts.types import ExportOptions, ExportReport, Surface
from arcavex.kernel.diagnostics import DiagnosticError, diagnostic


class PngExporter(Exporter):
    """Exports a rendered surface as a PNG file."""

    format: ClassVar[str] = "png"

    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport:
        """Encode ``surface`` to PNG at ``target`` and return a report."""
        image = surface.makeImageSnapshot()  # type: ignore[attr-defined]
        data = image.encodeToData(skia.EncodedImageFormat.kPNG, opts.quality)
        if data is None:
            raise DiagnosticError(
                diagnostic(
                    "ARC-EXP-001",
                    "PNG encoding failed",
                    hint="The surface could not be encoded to PNG.",
                )
            )
        payload = bytes(data)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with open(tmp, "wb") as handle:
            handle.write(payload)
        os.replace(tmp, target)
        return ExportReport(
            path=str(target),
            format="png",
            bytes_written=len(payload),
            content_sha256=hashlib.sha256(payload).hexdigest(),
        )

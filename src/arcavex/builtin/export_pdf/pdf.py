"""Raster-embedded RGB PDF exporter (spec §4.6, v1 policy).

Wraps the rendered raster surface in a single-page PDF at the correct physical page size and
bleed. The page geometry is authoritative: the trim size comes from the document canvas
(``page_width_pt``/``page_height_pt``), the media box grows outward by a uniform ``bleed_pt`` on
every side, and the embedded image is placed inside the trim box so the bleed margin frames it —
so an A4 + 3 mm document produces a 216 × 303 mm media box with a 210 × 297 mm trim box, ready
for a print workflow that reads those boxes.

The image is embedded at full render resolution (Skia stores an already-rasterized ``SkImage`` as
an XObject at its native pixels), so target DPI is preserved. Vector-preserving and CMYK/PDF-X
output is explicitly future work (spec §12): this exporter is raster-embedded RGB only.

Determinism (spec §4.6): the PDF carries only stable metadata — the engine version as
``/Producer``, the raster content hash as the render signature in ``/Subject``, and the sRGB
color policy in ``/Title`` — and no ``/CreationDate``, ``/ModDate``, or file ``/ID``. Skia's PDF
output and the box rewrite are both pure functions of the inputs, so identical renders produce
byte-identical PDFs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.builtin.export_pdf.boxes import rewrite_page_boxes
from arcavex.kernel.contracts.spi import Exporter
from arcavex.kernel.contracts.types import ExportOptions, ExportReport, Surface
from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.fsutil import atomic_write_bytes

_PT_PER_INCH = 72.0


class PdfExporter(Exporter):
    """Exports a rendered surface as a single-page, raster-embedded RGB PDF."""

    format: ClassVar[str] = "pdf"

    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport:
        """Embed ``surface`` in a PDF at ``target`` with correct physical size and bleed."""
        image = surface.makeImageSnapshot()  # type: ignore[attr-defined]
        px_w, px_h = image.width(), image.height()
        trim_w, trim_h = _trim_size_pt(px_w, px_h, opts)
        bleed = max(0.0, opts.bleed_pt)
        media_w, media_h = trim_w + 2.0 * bleed, trim_h + 2.0 * bleed

        # Render signature: the hash of the embedded raster, embedded as stable metadata so the
        # PDF is self-describing without leaking a timestamp or run id.
        signature = _raster_signature(image)
        raw = _build_pdf(image, media_w, media_h, trim_w, trim_h, bleed, opts, signature)

        media = (0.0, 0.0, media_w, media_h)
        trim = (bleed, bleed, bleed + trim_w, bleed + trim_h)
        payload = rewrite_page_boxes(raw, media, trim, media)

        atomic_write_bytes(Path(target), payload)
        return ExportReport(
            path=str(target),
            format="pdf",
            bytes_written=len(payload),
            content_sha256=hashlib.sha256(payload).hexdigest(),
        )


def _trim_size_pt(px_w: int, px_h: int, opts: ExportOptions) -> tuple[float, float]:
    """Resolve the physical trim size in points, preferring the document canvas size."""
    if opts.page_width_pt is not None and opts.page_height_pt is not None:
        return opts.page_width_pt, opts.page_height_pt
    # No physical size supplied: derive it from the pixel extent at the render DPI so the page is
    # still physically meaningful (a raw pixel canvas is treated as 72-dpi points by default).
    dpi = float(opts.dpi or 72)
    return px_w * _PT_PER_INCH / dpi, px_h * _PT_PER_INCH / dpi


def _raster_signature(image: object) -> str:
    """Return a stable hash of the embedded raster pixels (the render signature)."""
    png = image.encodeToData(skia.EncodedImageFormat.kPNG, 100)  # type: ignore[attr-defined]
    if png is None:
        raise DiagnosticError(
            diagnostic(
                "ARC-EXP-003",
                "PDF embedding failed",
                hint="The rendered surface could not be encoded for PDF embedding.",
            )
        )
    return hashlib.sha256(bytes(png)).hexdigest()


def _build_pdf(
    image: object,
    media_w: float,
    media_h: float,
    trim_w: float,
    trim_h: float,
    bleed: float,
    opts: ExportOptions,
    signature: str,
) -> bytes:
    """Draw ``image`` into a single-page PDF and return the raw (pre-rewrite) bytes."""
    stream = skia.DynamicMemoryWStream()
    metadata = skia.PDF.Metadata()
    metadata.fProducer = f"Arcavex {opts.engine_version}".strip()
    metadata.fCreator = metadata.fProducer
    metadata.fTitle = "color:sRGB"
    metadata.fSubject = f"render:{signature}"
    document = skia.PDF.MakeDocument(stream, metadata)
    if document is None:  # pragma: no cover - only on a broken skia build
        raise DiagnosticError(
            diagnostic(
                "ARC-EXP-003",
                "PDF document could not be created",
                hint="Skia's PDF backend is unavailable in this build.",
            )
        )
    canvas = document.beginPage(media_w, media_h)
    # Place the raster inside the trim box; the bleed margin frames it. Skia embeds the image at
    # its native resolution regardless of the page's point size, so DPI is preserved.
    dst = skia.Rect.MakeXYWH(bleed, bleed, trim_w, trim_h)
    canvas.drawImageRect(image, dst, skia.SamplingOptions())
    document.endPage()
    document.close()
    return bytes(stream.detachAsData())

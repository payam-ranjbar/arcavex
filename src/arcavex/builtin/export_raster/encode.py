"""Shared raster-encode and atomic-write helpers for the built-in image exporters.

The PNG, JPEG, and WebP exporters differ only in the Skia encoded format, the quality/lossless
handling, and whether alpha must be flattened first; everything else — snapshotting the surface,
encoding, writing the bytes atomically, and reporting the content hash — is identical and lives
here so a determinism-relevant change (how a surface becomes bytes on disk) can never apply to
one format and not the others. The encoded bytes carry no timestamps or run metadata, so
identical inputs produce byte-identical files (spec §4.6). Writes go through the shared
``fsutil.atomic_write_bytes`` (temp file beside the target, then ``os.replace``) so a reader
never sees a torn file and an interrupted export publishes nothing (spec §8.3).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import skia  # type: ignore[import-untyped]

from arcavex.kernel.contracts.types import ExportReport, Surface
from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.fsutil import atomic_write_bytes


def snapshot(surface: Surface) -> object:
    """Return the surface's image snapshot (the pixels to encode)."""
    return surface.makeImageSnapshot()  # type: ignore[attr-defined]


def flatten_over(image: object, background: skia.Color4f) -> object:
    """Composite ``image`` over an opaque ``background`` and return the flattened image.

    JPEG has no alpha channel, so a translucent render must be flattened onto a known opaque
    colour before encoding; doing it explicitly (rather than letting the encoder drop alpha
    against an undefined backdrop) keeps the result deterministic and predictable.
    """
    w, h = image.width(), image.height()  # type: ignore[attr-defined]
    surface = skia.Surface(w, h)
    canvas = surface.getCanvas()
    canvas.clear(background)
    canvas.drawImage(image, 0, 0)
    return surface.makeImageSnapshot()


def encode(image: object, image_format: object, quality: int, fmt: str) -> bytes:
    """Encode ``image`` to ``image_format`` at ``quality``; raise ``ARC-EXP-002`` on failure."""
    data = image.encodeToData(image_format, quality)  # type: ignore[attr-defined]
    if data is None:
        raise DiagnosticError(
            diagnostic(
                "ARC-EXP-002",
                f"{fmt.upper()} encoding failed",
                hint=f"The surface could not be encoded to {fmt.upper()}.",
            )
        )
    return bytes(data)


def write_report(payload: bytes, target: Path, fmt: str) -> ExportReport:
    """Write ``payload`` to ``target`` atomically and return the export report."""
    target = Path(target)
    atomic_write_bytes(target, payload)
    return ExportReport(
        path=str(target),
        format=fmt,
        bytes_written=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
    )

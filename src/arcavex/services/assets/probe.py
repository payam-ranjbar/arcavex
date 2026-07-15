"""Image header probing for decode guards.

Decode guards must reject an oversized image *before* it is decompressed (spec §4.7): "a
decoder that decompresses first and checks second is a security bug". So dimensions and format
are read from the file header here — a few dozen bytes — and the pixel budget is enforced
against those, never by decoding the whole image first. Only the small set of raster formats
Arcavex accepts are recognized; anything else is an undecodable-asset error.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic

# The raster formats Arcavex accepts (matches the compiler's image extension set).
ALLOWED_MIME = frozenset({"image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp"})


@dataclass(frozen=True)
class ImageProbe:
    """The format and pixel dimensions read from an image header."""

    mime: str
    width: int
    height: int

    @property
    def pixels(self) -> int:
        """Total decoded pixel count (width × height)."""
        return self.width * self.height


def probe_image(data: bytes, *, source: str) -> ImageProbe:
    """Return the ``mime``/``width``/``height`` read from an image header.

    Raises:
        DiagnosticError: ``ARC-AST-002`` when the bytes are not a recognized, well-formed
            image header of a supported format.
    """
    for detect in (_png, _gif, _bmp, _webp, _jpeg):
        probe = detect(data)
        if probe is not None:
            if probe.width <= 0 or probe.height <= 0:
                raise _undecodable(source, "header reports non-positive dimensions")
            return probe
    raise _undecodable(source, "unrecognized or unsupported image format")


def _undecodable(source: str, detail: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-AST-002",
            f"Image asset could not be decoded: {source} ({detail})",
            file=source,
            hint="Provide a supported, undamaged image (PNG, JPEG, GIF, BMP, or WEBP).",
        )
    )


def _png(data: bytes) -> ImageProbe | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return ImageProbe("image/png", width, height)


def _gif(data: bytes) -> ImageProbe | None:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return ImageProbe("image/gif", width, height)


def _bmp(data: bytes) -> ImageProbe | None:
    if len(data) < 26 or data[:2] != b"BM":
        return None
    width, height = struct.unpack("<ii", data[18:26])
    return ImageProbe("image/bmp", width, abs(height))


def _webp(data: bytes) -> ImageProbe | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        # Canvas dimensions are stored minus one, 24-bit little-endian.
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return ImageProbe("image/webp", w, h)
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return ImageProbe("image/webp", w, h)
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        w = int.from_bytes(data[26:28], "little") & 0x3FFF
        h = int.from_bytes(data[28:30], "little") & 0x3FFF
        return ImageProbe("image/webp", w, h)
    return None


def _jpeg(data: bytes) -> ImageProbe | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # Start-of-frame markers carry the dimensions (skip the differential/arithmetic gaps).
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return ImageProbe("image/jpeg", width, height)
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + seg_len
    return None

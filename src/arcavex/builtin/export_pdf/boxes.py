"""Deterministic PDF page-box rewriter.

Skia's PDF backend emits only a ``/MediaBox``, and it quantizes that box to whole raster pixels
(so an A4 page of 595.28 pt is written as an integer 595) — neither the exact fractional physical
size nor the ``/TrimBox`` and ``/BleedBox`` that a print PDF with bleed must carry (spec §4.6).
Rather than fight the backend, we let it produce a correct *content* stream and then rewrite the
page dictionary here: replace the ``/MediaBox`` with the exact physical size and inject the trim
and bleed boxes.

Because inserting bytes shifts every following object's offset, the classic cross-reference table
is rebuilt from scratch by rescanning object positions — so the result is a valid PDF a real
reader (PDFium, Ghostscript) opens, not just a byte blob. The output is a pure function of the
input bytes and the box geometry: no timestamps, no run ids, so identical inputs stay
byte-identical (spec §4.6). If the input does not match the expected classic-xref shape the
rewrite raises rather than emit a corrupt file.
"""

from __future__ import annotations

import re

Box = tuple[float, float, float, float]

_PAGE_MARKER = re.compile(rb"/Type\s*/Page(?![s])")
_MEDIABOX = re.compile(rb"/MediaBox\s*\[[^\]]*\]")
_OBJ = re.compile(rb"\n(\d+) 0 obj")
_ROOT = re.compile(rb"/Root\s+(\d+)\s+0\s+R")
_INFO = re.compile(rb"/Info\s+(\d+)\s+0\s+R")


class PdfRewriteError(ValueError):
    """The PDF did not match the classic single-xref shape the rewriter supports."""


def _fmt(value: float) -> str:
    """Format a coordinate stably: round to 6 dp, strip trailing zeros, collapse ``-0``."""
    rounded = round(value, 6)
    if rounded == 0.0:
        rounded = 0.0
    text = f"{rounded:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _box(box: Box) -> bytes:
    return ("[" + " ".join(_fmt(v) for v in box) + "]").encode("ascii")


def rewrite_page_boxes(pdf: bytes, media: Box, trim: Box, bleed: Box) -> bytes:
    """Return ``pdf`` with the page ``MediaBox`` set to ``media`` plus ``TrimBox``/``BleedBox``.

    The xref table and trailer are rebuilt so the file stays valid. Raises
    :class:`PdfRewriteError` if the input is not a single-page classic-xref PDF.
    """
    page = _PAGE_MARKER.search(pdf)
    if page is None:
        raise PdfRewriteError("no /Type /Page object found")
    mbox = _MEDIABOX.search(pdf, page.start())
    if mbox is None:
        raise PdfRewriteError("page has no /MediaBox")
    replacement = (
        b"/MediaBox " + _box(media) + b"\n/TrimBox " + _box(trim) + b"\n/BleedBox " + _box(bleed)
    )
    body = pdf[: mbox.start()] + replacement + pdf[mbox.end() :]

    xref_kw = body.rfind(b"\nxref\n")
    if xref_kw == -1:
        raise PdfRewriteError("no classic xref table")
    trailer = pdf[pdf.rfind(b"trailer") :]
    root_m = _ROOT.search(trailer)
    if root_m is None:
        raise PdfRewriteError("trailer has no /Root")
    info_m = _INFO.search(trailer)

    body = body[:xref_kw] + b"\n"
    offsets: dict[int, int] = {}
    for match in _OBJ.finditer(body):
        # The object's byte offset is the position of its number (one past the leading newline).
        offsets[int(match.group(1))] = match.start() + 1
    if not offsets:
        raise PdfRewriteError("no indirect objects found")

    size = max(offsets) + 1
    startxref = len(body)
    lines = [b"xref", f"0 {size}".encode("ascii"), b"0000000000 65535 f "]
    for num in range(1, size):
        offset = offsets.get(num)
        if offset is None:
            lines.append(b"0000000000 00000 f ")
        else:
            lines.append(f"{offset:010d} 00000 n ".encode("ascii"))
    xref = b"\n".join(lines) + b"\n"

    trailer_out = f"trailer\n<</Size {size}\n/Root {root_m.group(1).decode()} 0 R"
    if info_m is not None:
        trailer_out += f"\n/Info {info_m.group(1).decode()} 0 R"
    trailer_out += ">>\n"
    tail = f"startxref\n{startxref}\n%%EOF\n"
    return body + xref + trailer_out.encode("ascii") + tail.encode("ascii")

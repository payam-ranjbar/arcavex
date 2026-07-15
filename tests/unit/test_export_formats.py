"""Exporter tests: JPEG/WebP/PDF output, determinism, PDF physical size and bleed boxes.

Determinism is a release gate (spec §4.6): identical inputs must produce byte-identical files in
every format, with no embedded timestamps or run ids. The PDF exporter additionally must carry the
correct physical page size and trim/bleed boxes (§3.1.2 print-first), which these tests assert by
parsing the produced PDF and confirming a real cross-reference table points at every object.
"""

from __future__ import annotations

import re
from pathlib import Path

import skia

from arcavex.bootstrap import build_facade
from arcavex.builtin.export_pdf import PdfExporter
from arcavex.builtin.export_raster import JpegExporter, WebpExporter
from arcavex.kernel.contracts.types import ExportOptions

_MM_TO_PT = 72.0 / 25.4

_TEMPLATE = """\
version: 0.1.0
formats:
  a4:
    canvas: {width: 210mm, height: 297mm, dpi: 300, bleed: 3mm}
  square:
    canvas: {width: 400px, height: 400px, dpi: 72}
root:
  type: group
  id: root
  children:
    - id: background
      type: shape
      shape: rect
      style: {fill: "#e94560"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
    - id: dot
      type: shape
      shape: circle
      style: {fill: "#1a1a2e"}
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 120px, h: 120px}
"""


def _template(tmp_path: Path) -> Path:
    path = tmp_path / "poster.yaml"
    path.write_text(_TEMPLATE, encoding="utf-8")
    return path


def _surface() -> skia.Surface:
    surface = skia.Surface(64, 48)
    canvas = surface.getCanvas()
    canvas.clear(skia.Color4f(1, 1, 1, 1))
    paint = skia.Paint()
    paint.setColor(skia.ColorRED)
    canvas.drawRect(skia.Rect.MakeXYWH(4, 4, 30, 20), paint)
    return surface


# --------------------------------------------------------------------- raster formats
def test_jpeg_export_writes_valid_deterministic_file(tmp_path: Path) -> None:
    exporter = JpegExporter()
    a = exporter.export(_surface(), tmp_path / "a.jpg", ExportOptions(quality=85))
    b = exporter.export(_surface(), tmp_path / "b.jpg", ExportOptions(quality=85))
    data = Path(a.path).read_bytes()
    assert data[:2] == b"\xff\xd8"  # JPEG SOI marker
    assert a.format == "jpeg"
    assert a.content_sha256 == b.content_sha256  # byte-identical reruns


def test_jpeg_quality_changes_size(tmp_path: Path) -> None:
    low = JpegExporter().export(_surface(), tmp_path / "lo.jpg", ExportOptions(quality=10))
    high = JpegExporter().export(_surface(), tmp_path / "hi.jpg", ExportOptions(quality=95))
    assert low.bytes_written != high.bytes_written


def test_webp_export_deterministic(tmp_path: Path) -> None:
    exporter = WebpExporter()
    a = exporter.export(_surface(), tmp_path / "a.webp", ExportOptions(quality=80))
    b = exporter.export(_surface(), tmp_path / "b.webp", ExportOptions(quality=80))
    assert Path(a.path).read_bytes()[:4] == b"RIFF"
    assert a.content_sha256 == b.content_sha256


def test_webp_lossless_is_bit_exact(tmp_path: Path) -> None:
    """Lossless WebP round-trips to the exact source pixels (spec: honoured, not approximated)."""
    surface = _surface()
    report = WebpExporter().export(surface, tmp_path / "ll.webp", ExportOptions(lossless=True))
    decoded = skia.Image.MakeFromEncoded(
        skia.Data.MakeFromFileName(str(report.path))
    ).toarray()
    original = surface.makeImageSnapshot().toarray()
    assert (decoded == original).all()


# --------------------------------------------------------------------------- PDF export
def test_pdf_physical_size_and_bleed_boxes(tmp_path: Path) -> None:
    """A4 + 3 mm bleed produces a 216×303 mm media box and a 210×297 mm trim box."""
    facade = build_facade()
    out = tmp_path / "poster.pdf"
    result = facade.render_file(_template(tmp_path), format_name="a4", output=out)
    assert result.ok, result.diagnostics
    data = out.read_bytes()
    assert data[:5] == b"%PDF-"

    media = _box(data, "MediaBox")
    trim = _box(data, "TrimBox")
    bleed = _box(data, "BleedBox")
    trim_w, trim_h = 210 * _MM_TO_PT, 297 * _MM_TO_PT
    bleed_pt = 3 * _MM_TO_PT
    assert media == _approx(0, 0, trim_w + 2 * bleed_pt, trim_h + 2 * bleed_pt)
    assert trim == _approx(bleed_pt, bleed_pt, bleed_pt + trim_w, bleed_pt + trim_h)
    assert bleed == media  # bleed box spans the whole media in v1


def test_pdf_no_bleed_trim_equals_media(tmp_path: Path) -> None:
    facade = build_facade()
    out = tmp_path / "square.pdf"
    result = facade.render_file(_template(tmp_path), format_name="square", output=out)
    assert result.ok, result.diagnostics
    data = out.read_bytes()
    assert _box(data, "MediaBox") == _box(data, "TrimBox")


def test_pdf_carries_no_timestamps_and_is_deterministic(tmp_path: Path) -> None:
    facade = build_facade()
    template = _template(tmp_path)
    first = facade.render_file(template, format_name="a4", output=tmp_path / "one.pdf")
    second = facade.render_file(template, format_name="a4", output=tmp_path / "two.pdf")
    assert first.content_sha256 == second.content_sha256
    data = (tmp_path / "one.pdf").read_bytes()
    assert b"/CreationDate" not in data
    assert b"/ModDate" not in data
    assert b"/ID" not in data
    # Stable metadata is present: the engine version as Producer.
    assert b"/Producer (Arcavex" in data


def test_pdf_xref_is_valid(tmp_path: Path) -> None:
    """The rebuilt cross-reference table points at every object it lists (a real reader opens)."""
    exporter = PdfExporter()
    report = exporter.export(
        _surface(),
        tmp_path / "x.pdf",
        ExportOptions(page_width_pt=595.276, page_height_pt=841.89, bleed_pt=8.5),
    )
    data = Path(report.path).read_bytes()
    _assert_valid_xref(data)


# --------------------------------------------------------------------------- helpers
def _box(pdf: bytes, name: str) -> tuple[float, ...]:
    match = re.search(rf"/{name} \[([^\]]*)\]".encode(), pdf)
    assert match is not None, f"missing /{name}"
    return tuple(round(float(v), 3) for v in match.group(1).split())


def _approx(*values: float) -> tuple[float, ...]:
    return tuple(round(v, 3) for v in values)


def _assert_valid_xref(pdf: bytes) -> None:
    start = int(re.search(rb"startxref\s+(\d+)", pdf).group(1))
    assert pdf[start : start + 4] == b"xref"
    header = re.match(rb"xref\n0 (\d+)\n", pdf[start:])
    assert header is not None
    count = int(header.group(1))
    pos = start + header.end()
    for num in range(count):
        entry = pdf[pos : pos + 20]
        pos += 20
        offset = int(entry[:10])
        kind = entry[17:18]
        if kind == b"n":
            assert re.match(rb"%d 0 obj" % num, pdf[offset : offset + 30]), f"object {num} offset"

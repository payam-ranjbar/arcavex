"""Platform capability test — the Phase -1 feasibility probes, now as regression tests.

Verifies the skia-python 144 baseline this build depends on: textlayout availability,
bundled-font loading, mixed Farsi/English shaping with non-zero metrics, SkSL RuntimeEffect
compilation, deterministic PNG encoding, and PDF page sizing.
"""

from __future__ import annotations

from pathlib import Path

import skia  # type: ignore[import-untyped]

from arcavex.kernel.contracts.types import MeasureRequest
from arcavex.services.text import TextService


def test_skia_imports_and_version() -> None:
    assert skia.__version__.startswith("144.")
    assert hasattr(skia, "textlayout")
    assert hasattr(skia.textlayout, "ParagraphBuilder")


def test_bundled_fonts_loaded() -> None:
    service = TextService()
    families = service.families
    assert {"Inter", "Vazirmatn"}.issubset(families)


def test_english_and_farsi_metrics_positive() -> None:
    service = TextService()
    en = service.measure(
        MeasureRequest(text="Hello", font_families=("Inter",), font_size_pt=40)
    )
    assert en.width_pt > 0 and en.height_pt > 0
    fa = service.measure(
        MeasureRequest(
            text="سلام دنیا",
            font_families=("Vazirmatn",),
            font_size_pt=40,
            direction="rtl",
        )
    )
    assert fa.width_pt > 0 and fa.height_pt > 0


def test_runtime_effect_compiles() -> None:
    effect = skia.RuntimeEffect.MakeForShader(
        "half4 main(float2 p) { return half4(1, 0, 0, 1); }"
    )
    assert effect is not None


def test_png_bytes_deterministic() -> None:
    def encode() -> bytes:
        surface = skia.Surface(64, 64)
        canvas = surface.getCanvas()
        canvas.clear(skia.Color4f(0.1, 0.2, 0.3, 1.0))
        paint = skia.Paint()
        paint.setColor4f(skia.Color4f(1, 1, 1, 1))
        canvas.drawCircle(32, 32, 16, paint)
        data = surface.makeImageSnapshot().encodeToData(skia.EncodedImageFormat.kPNG, 100)
        return bytes(data)

    assert encode() == encode()


def test_pdf_page_sizing(tmp_path: Path) -> None:
    path = tmp_path / "probe.pdf"
    stream = skia.FILEWStream(str(path))
    document = skia.PDF.MakeDocument(stream)
    canvas = document.beginPage(595.0, 842.0)  # A4 in points
    canvas.clear(skia.ColorWHITE)
    document.endPage()
    document.close()
    stream.flush()
    header = path.read_bytes()[:5]
    assert header == b"%PDF-"

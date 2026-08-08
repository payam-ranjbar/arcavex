"""ARC-AST-020: an asset that is mostly transparent padding under contain/cover.

The reference case is a 512x512 asset whose artwork is a 452x114 band — 19.7% opaque.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import skia  # type: ignore[import-untyped]

from arcavex.services.assets.alpha import COVERAGE_WARN_BELOW, opaque_box
from arcavex.services.template.compiler import Compiler
from arcavex.services.text import TextService

_TS = TextService()


def _write_png(path: Path, array: np.ndarray) -> Path:
    skia.Image.fromarray(array, colorType=skia.kRGBA_8888_ColorType).save(str(path), skia.kPNG)
    return path


def _banded(path: Path, canvas: int = 512, band_w: int = 452, band_h: int = 114) -> Path:
    """A wide, short opaque band centred in a large transparent square."""
    array = np.zeros((canvas, canvas, 4), dtype=np.uint8)
    top, left = (canvas - band_h) // 2, (canvas - band_w) // 2
    array[top : top + band_h, left : left + band_w] = [255, 0, 0, 255]
    return _write_png(path, array)


def _full(path: Path, size: int = 128) -> Path:
    return _write_png(path, np.full((size, size, 4), 255, dtype=np.uint8))


# ------------------------------------------------------------------ the measurement itself
def test_opaque_box_finds_the_band(tmp_path: Path) -> None:
    box = opaque_box(_banded(tmp_path / "logo.png"))
    assert box is not None
    assert (box.width, box.height) == (452, 114)
    assert (box.canvas_width, box.canvas_height) == (512, 512)
    assert box.coverage == pytest.approx(452 * 114 / (512 * 512), abs=1e-6)
    assert box.coverage < COVERAGE_WARN_BELOW


def test_opaque_box_of_an_image_with_no_transparency_is_the_whole_canvas(tmp_path: Path) -> None:
    box = opaque_box(_full(tmp_path / "photo.png"))
    assert box is not None
    assert box.coverage == pytest.approx(1.0)


def test_antialiasing_halo_does_not_inflate_the_box(tmp_path: Path) -> None:
    """Anti-aliased edges leave alpha 1-3 pixels; thresholding at >0 would measure 100%."""
    canvas = 512
    array = np.zeros((canvas, canvas, 4), dtype=np.uint8)
    array[199:313, 30:482] = [255, 0, 0, 255]
    array[0, 0] = [255, 0, 0, 3]
    array[canvas - 1, canvas - 1] = [255, 0, 0, 1]
    box = opaque_box(_write_png(tmp_path / "halo.png", array))
    assert box is not None
    assert (box.width, box.height) == (452, 114)


def test_fully_transparent_image_reports_nothing(tmp_path: Path) -> None:
    empty = _write_png(tmp_path / "empty.png", np.zeros((64, 64, 4), dtype=np.uint8))
    assert opaque_box(empty) is None


def test_unreadable_path_is_silent_not_an_error(tmp_path: Path) -> None:
    assert opaque_box(tmp_path / "does-not-exist.png") is None


# ------------------------------------------------------------------ the diagnostic
_TEMPLATE = """
version: 0.1.0
formats:
  square: {canvas: {width: 400px, height: 400px, dpi: 72}}
root:
  type: group
  id: root
  children:
    - id: mark
      type: image
      asset: %s
      fit: %s
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 300pt, h: 300pt}
"""


def padding_warnings(tmp_path: Path, asset: str, fit: str) -> list:
    """Compile the one-image template and return only its ARC-AST-020 diagnostics."""
    template = tmp_path / "t.yaml"
    template.write_text(_TEMPLATE % (asset, fit), encoding="utf-8")
    result = Compiler(available_fonts=frozenset(_TS.families)).compile(
        template, None, "square", None, None
    )
    assert result.document is not None, result.diagnostics
    return [d for d in result.diagnostics if d.code == "ARC-AST-020"]


@pytest.mark.parametrize("fit", ["contain", "cover"])
def test_padded_asset_warns_under_contain_and_cover(tmp_path: Path, fit: str) -> None:
    _banded(tmp_path / "logo.png")
    warnings = padding_warnings(tmp_path, "logo.png", fit)
    assert len(warnings) == 1
    diag = warnings[0]
    assert diag.code == "ARC-AST-020"
    assert diag.severity == "warning"
    assert "512x512" in diag.message
    assert "452x114" in diag.message
    assert "20%" in diag.message
    assert f"'fit: {fit}'" in diag.message
    assert "mark" in diag.message  # the node id, so an agent can address it
    assert diag.hint is not None and "alpha bounding box" in diag.hint


def test_fill_is_not_warned_about(tmp_path: Path) -> None:
    """'fill' does not preserve aspect, so padding distorts rather than shrinks the artwork."""
    _banded(tmp_path / "logo.png")
    assert padding_warnings(tmp_path, "logo.png", "fill") == []


def test_ordinary_asset_produces_no_warning(tmp_path: Path) -> None:
    _full(tmp_path / "photo.png")
    assert padding_warnings(tmp_path, "photo.png", "contain") == []


def test_generous_but_reasonable_margin_is_not_warned_about(tmp_path: Path) -> None:
    """Artwork with an ordinary margin must stay clear of the threshold."""
    canvas = 200
    array = np.zeros((canvas, canvas, 4), dtype=np.uint8)
    array[20:180, 20:180] = [0, 0, 255, 255]  # 160x160 in 200x200 = 64% coverage
    _write_png(tmp_path / "margin.png", array)
    assert padding_warnings(tmp_path, "margin.png", "contain") == []


def test_no_bundled_asset_trips_the_warning() -> None:
    """Calibration guard for COVERAGE_WARN_BELOW.

    The threshold sits below the lowest-coverage shipped asset (0.444) and above the reference
    case (0.197). An asset landing in that gap fails here, so the number is re-derived from
    measurement rather than left to drift.
    """
    repo_root = Path(__file__).resolve().parents[2]
    offenders = []
    roots = [repo_root / "examples", repo_root / "tests" / "fixtures"]
    for path in sorted(p for root in roots for p in root.rglob("*.png")):
        box = opaque_box(path)
        if box is not None and box.coverage < COVERAGE_WARN_BELOW:
            offenders.append(f"{path.relative_to(repo_root)} at {box.coverage:.1%}")
    assert not offenders, "bundled assets below the warning threshold: " + ", ".join(offenders)


def test_warning_is_located_at_the_node(tmp_path: Path) -> None:
    _banded(tmp_path / "logo.png")
    diag = padding_warnings(tmp_path, "logo.png", "contain")[0]
    assert diag.source is not None
    assert diag.source.file is not None and diag.source.file.endswith("t.yaml")
    assert diag.source.line is not None and diag.source.line > 0
    assert diag.source.keypath is not None

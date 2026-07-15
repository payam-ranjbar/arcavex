"""File-safety suite (spec §8.5): path traversal, malformed assets, and atomic/interrupted writes.

Arcavex is a local tool, so safety means resisting malformed inputs and accidental corruption, not
tenant isolation. These tests exercise the guarantees that protect the filesystem: a template
cannot read outside its own directory, a broken image fails with a located diagnostic rather than a
crash, and an export either lands whole or leaves the previous file untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import skia

from arcavex.bootstrap import build_facade
from arcavex.builtin.export_raster import PngExporter
from arcavex.kernel.contracts.types import ExportOptions

_TEMPLATE = """\
version: 0.1.0
formats:
  square:
    canvas: {{width: 200px, height: 200px, dpi: 72}}
root:
  type: group
  id: root
  children:
    - id: photo
      type: image
      asset: {asset}
      fit: cover
      constraints:
        anchor: {{top: parent.top, left: parent.left}}
        size: {{w: fill, h: fill}}
"""


def _template(dir_: Path, asset: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / "template.yaml"
    path.write_text(_TEMPLATE.format(asset=asset), encoding="utf-8")
    return path


def _surface() -> skia.Surface:
    surface = skia.Surface(16, 16)
    surface.getCanvas().clear(skia.Color4f(0, 0, 0, 1))
    return surface


# ---------------------------------------------------------------------- path traversal
def test_asset_path_traversal_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "secret.png").write_bytes(b"not really a png but exists")
    template = _template(tmp_path / "tpl", asset="../secret.png")
    diagnostics = build_facade().validate_template(template, format_name="square")
    codes = [d.code for d in diagnostics]
    assert "ARC-AST-004" in codes


def test_symlink_traversal_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside the template root")
    tpl_dir = tmp_path / "tpl"
    tpl_dir.mkdir()
    link = tpl_dir / "link.png"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    template = _template(tpl_dir, asset="link.png")
    codes = [d.code for d in build_facade().validate_template(template, format_name="square")]
    assert "ARC-AST-004" in codes


# ----------------------------------------------------------------------- malformed asset
def test_malformed_asset_is_a_located_diagnostic(tmp_path: Path) -> None:
    tpl_dir = tmp_path / "tpl"
    tpl_dir.mkdir()
    (tpl_dir / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\n garbage not a real image")
    template = _template(tpl_dir, asset="broken.png")
    result = build_facade().render_file(
        template, format_name="square", output=tmp_path / "out.png"
    )
    assert not result.ok
    assert any(d.code == "ARC-AST-002" for d in result.diagnostics)
    assert not (tmp_path / "out.png").exists()


# ---------------------------------------------------------------------- atomic writes
def test_export_leaves_no_temp_file(tmp_path: Path) -> None:
    PngExporter().export(_surface(), tmp_path / "ok.png", ExportOptions())
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp" or ".tmp" in p.name]
    assert leftovers == []


def test_interrupted_export_leaves_prior_file_intact(tmp_path: Path, monkeypatch) -> None:
    """An export interrupted mid-write publishes nothing: the previous file stays untouched."""
    target = tmp_path / "poster.png"
    target.write_bytes(b"PREEXISTING")

    import arcavex.services.fsutil as fsutil

    def _boom(src: str, dst: str) -> None:
        raise OSError("simulated interruption during publish")

    monkeypatch.setattr(fsutil.os, "replace", _boom)
    with pytest.raises(OSError):
        PngExporter().export(_surface(), target, ExportOptions())

    assert target.read_bytes() == b"PREEXISTING"  # original intact
    # No partial temp file survives the interruption.
    assert [p.name for p in tmp_path.iterdir()] == ["poster.png"]

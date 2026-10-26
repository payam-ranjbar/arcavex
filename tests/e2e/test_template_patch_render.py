"""Render-level proof that a scoped patch changes only its own format (A5).

The unit-visible assertion is that ``--format square`` writes into ``formats.square.patch``; the
guarantee that actually matters is that the *pixels* of the other formats do not move. These
tests render the same two-format template before and after a scoped patch and compare the
content hash, so a patch that leaked into the root would show up here even if the YAML looked
right.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arcavex.bootstrap import build_facade
from arcavex.clients.cli import app

runner = CliRunner()

_TWO_FORMATS = """version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 96}}
  story: {canvas: {width: 200px, height: 300px, dpi: 96}}
locales: {en: {direction: ltr}}
preview_data: {}
root:
  id: root
  type: group
  children:
    - id: title
      type: text
      text: Hello
      style: {font: Inter, font_size: 20pt, color: "#111111"}
      constraints:
        anchor: {top: parent.top, start: parent.start}
        size: {w: fill, h: fit_content}
"""


def _render_sha(template: Path, fmt: str, out: Path) -> str:
    """Render ``template`` in ``fmt`` and return the image content hash (fails loudly)."""
    result = build_facade().render_file(template, format_name=fmt, locale="en", output=out)
    assert result.ok, result.diagnostics
    assert result.content_sha256
    return result.content_sha256


def test_format_patch_changes_only_its_format(tmp_path: Path, arcavex_home: Path) -> None:
    """--format square moves the square render and leaves story byte-identical."""
    template = tmp_path / "template.yaml"
    template.write_text(_TWO_FORMATS, encoding="utf-8")

    square_before = _render_sha(template, "square", tmp_path / "square-before.png")
    story_before = _render_sha(template, "story", tmp_path / "story-before.png")

    patched = runner.invoke(
        app,
        [
            "template", "patch", str(template), "--format", "square",
            "--set", "nodes.title.style.font_size", "--value", '"40pt"',
        ],
    )
    assert patched.exit_code == 0, patched.output

    square_after = _render_sha(template, "square", tmp_path / "square-after.png")
    story_after = _render_sha(template, "story", tmp_path / "story-after.png")

    assert square_after != square_before
    assert story_after == story_before

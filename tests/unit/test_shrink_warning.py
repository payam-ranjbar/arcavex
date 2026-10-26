"""Facade-level tests for ARC-LAY-058: a converged 'shrink_to_fit' below the declared size.

A3: validation must not treat shrunk text as silently valid. The solver emits a warning that
names the node, the format, the declared size and the rendered size. These tests pin the
facade path that surfaces it and the fit path that must stay quiet.
"""

from __future__ import annotations

from pathlib import Path

from arcavex.bootstrap import build_facade

_FORMAT = "formats: {square: {canvas: {width: 400px, height: 400px, dpi: 96}}}\n"

# 48pt headline in a 200x70pt box: the measure test in tests/unit/test_text_fit.py proves this
# shrinks and converges, so the solver must report ARC-LAY-058.
_SHRINK_BODY = (
    "root:\n"
    "  id: root\n"
    "  type: group\n"
    "  children:\n"
    "    - id: headline\n"
    "      type: text\n"
    '      text: "A rather long headline that will not fit at one size"\n'
    "      style: {font: Inter, font_size: 48pt, color: black}\n"
    "      fit: {policy: shrink_to_fit, min_size: 10pt}\n"
    "      constraints: {anchor: {top: parent.top, left: parent.left}, "
    "size: {w: 200pt, h: 70pt}}\n"
)

# The same node with room to spare: no shrink, so no ARC-LAY-058.
_FITS_BODY = _SHRINK_BODY.replace("size: {w: 200pt, h: 70pt}", "size: {w: 600pt, h: 200pt}")


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "t.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_validate_template_surfaces_shrink_warning(tmp_path: Path) -> None:
    template = _write(tmp_path, _FORMAT + _SHRINK_BODY)
    diags = build_facade().validate_template(template, None, "square", None, None)
    warnings = [d for d in diags if d.code == "ARC-LAY-058"]
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.severity == "warning"
    assert "'headline'" in warning.message
    assert "'square'" in warning.message
    assert "declared" in warning.message
    assert "rendered" in warning.message
    assert "48.0pt" in warning.message


def test_validate_template_no_warning_when_format_fits(tmp_path: Path) -> None:
    template = _write(tmp_path, _FORMAT + _FITS_BODY)
    diags = build_facade().validate_template(template, None, "square", None, None)
    assert not any(d.code == "ARC-LAY-058" for d in diags)

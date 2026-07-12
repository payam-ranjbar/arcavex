"""Variable schema enforcement tests: type matrix, RR-1, RR-2, enum, defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.services.template.compiler import Compiler


def _template(tmp_path: Path, variables: str, extra_data: str = "") -> tuple[Path, Path]:
    template = tmp_path / "template.yaml"
    template.write_text(
        "version: 0.1.0\n"
        f"variables:\n{variables}"
        "formats:\n  square: {canvas: {width: 100px, height: 100px, dpi: 96}}\n"
        "root: {type: group, id: root, children: []}\n",
        encoding="utf-8",
    )
    data = tmp_path / "data.yaml"
    data.write_text(extra_data, encoding="utf-8")
    return template, data


def _codes(tmp_path: Path, variables: str, data: str) -> list[str]:
    template, data_path = _template(tmp_path, variables, data)
    result = Compiler().compile(template, data_path, "square", None, None)
    return [d.code for d in result.diagnostics]


@pytest.mark.parametrize(
    ("decl_type", "value", "ok"),
    [
        ("string", '"hi"', True),
        ("number", "3", True),
        ("number", "3.5", True),
        ("number", "true", False),
        ("boolean", "true", True),
        ("boolean", "1", False),
        ("list", "[1, 2]", True),
        ("list", '"x"', False),
        ("object", "{a: 1}", True),
        ("color", '"#fff"', True),
        ("image", '"a.png"', True),
    ],
)
def test_type_matrix(tmp_path: Path, decl_type: str, value: str, ok: bool) -> None:
    codes = _codes(tmp_path, f"  v: {{type: {decl_type}}}\n", f"v: {value}\n")
    has_mismatch = "ARC-TPL-015" in codes
    assert has_mismatch != ok


def test_unknown_type_is_located_error(tmp_path: Path) -> None:
    """RR-1: a typo'd declared type is a located error, not a silent skip."""
    template, _ = _template(tmp_path, "  v: {type: strnig}\n")
    result = Compiler().compile(template, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-016")
    assert diag.source is not None and diag.source.keypath == "v"
    assert "strnig" in diag.message


def test_number_for_string_coerces_with_warning(tmp_path: Path) -> None:
    """RR-2: a number for a declared string coerces with a warning, not an error."""
    template, data = _template(tmp_path, "  v: {type: string}\n", "v: 2026\n")
    result = Compiler().compile(template, data, "square", None, None)
    warnings = [d for d in result.diagnostics if not d.is_error()]
    assert any(d.code == "ARC-TPL-018" for d in warnings)
    assert not any(d.code == "ARC-TPL-015" for d in result.diagnostics)


def test_string_for_number_stays_hard_error(tmp_path: Path) -> None:
    codes = _codes(tmp_path, "  v: {type: number}\n", 'v: "nope"\n')
    assert "ARC-TPL-015" in codes


def test_enum_violation_is_error(tmp_path: Path) -> None:
    codes = _codes(
        tmp_path, "  size: {type: string, enum: [small, large]}\n", "size: medium\n"
    )
    assert "ARC-TPL-017" in codes


def test_enum_allows_listed_value(tmp_path: Path) -> None:
    codes = _codes(
        tmp_path, "  size: {type: string, enum: [small, large]}\n", "size: small\n"
    )
    assert "ARC-TPL-017" not in codes


def test_default_is_type_checked(tmp_path: Path) -> None:
    """A default of the wrong declared type is reported at the declaration site."""
    template, _ = _template(tmp_path, "  v: {type: number, default: notanumber}\n")
    result = Compiler().compile(template, None, "square", None, None)
    diag = next((d for d in result.diagnostics if d.code == "ARC-TPL-015"), None)
    assert diag is not None
    assert diag.source is not None and diag.source.file.endswith("template.yaml")

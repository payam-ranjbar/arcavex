"""Locale system tests: data-overlay merge, digits, direction, and font overrides."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml.comments import TaggedScalar
from ruamel.yaml.tag import Tag

from arcavex.services.template.compiler import Compiler
from arcavex.services.template.overlays import merge_overlay


def _delete_marker() -> TaggedScalar:
    """A YAML ``!delete`` tagged scalar, as the loader produces for ``key: !delete``."""
    return TaggedScalar(value="", style=None, tag=Tag(suffix="!delete"))


# ------------------------------------------------------------ overlay merge semantics
def test_mapping_merge_recursive() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    overlay = {"a": {"y": 20, "z": 30}}
    assert merge_overlay(base, overlay) == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3}


def test_scalar_replaces_and_list_replaces_whole() -> None:
    base = {"n": 1, "items": [1, 2, 3]}
    overlay = {"n": 9, "items": [4]}
    assert merge_overlay(base, overlay) == {"n": 9, "items": [4]}


def test_delete_marker_removes_key() -> None:
    # CR-17: only the explicit YAML tag `!delete` removes a key.
    base = {"keep": 1, "drop": 2}
    assert merge_overlay(base, {"drop": _delete_marker()}) == {"keep": 1}


def test_plain_delete_string_is_a_value_not_deletion() -> None:
    # CR-17: the plain string "!delete" is ordinary data, so it stays representable.
    base = {"keep": 1, "note": "old"}
    assert merge_overlay(base, {"note": "!delete"}) == {"keep": 1, "note": "!delete"}


def test_null_is_a_value_not_deletion() -> None:
    base = {"a": 1}
    assert merge_overlay(base, {"a": None}) == {"a": None}


# ------------------------------------------------------------ locale application
_TPL = """
version: 0.1.0
variables:
  hour: {type: number, default: 17}
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
locales:
  en: {direction: ltr}
  fa:
    direction: rtl
    digits: fa
    fonts: {Inter: [Vazirmatn, Inter]}
    data: {hour: 19}
preview_data: {hour: 17}
root:
  type: group
  id: root
  children:
    - id: label
      type: text
      text: "hour {{ hour }}"
      style: {font: Inter, font_size: 20px, color: black}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
"""


def _label(tmp_path: Path, locale: str | None):  # noqa: ANN202
    template = tmp_path / "t.yaml"
    template.write_text(_TPL, encoding="utf-8")
    result = Compiler().compile(template, None, "square", locale, None)
    assert result.document is not None, result.diagnostics
    return result.document, result.document.root.children[0]


def test_locale_direction_sets_root_default(tmp_path: Path) -> None:
    doc, _ = _label(tmp_path, "fa")
    assert doc.root.direction == "rtl"
    doc_en, _ = _label(tmp_path, "en")
    assert doc_en.root.direction == "ltr"


def test_locale_data_overlay_and_fa_digits(tmp_path: Path) -> None:
    _, label = _label(tmp_path, "fa")
    # data overlay set hour=19, and fa digits map it: "hour ۱۹".
    assert "۱۹" in label.text
    assert "19" not in label.text


def test_locale_font_override(tmp_path: Path) -> None:
    _, label = _label(tmp_path, "fa")
    assert label.style.font_families == ("Vazirmatn", "Inter")
    _, en = _label(tmp_path, "en")
    assert en.style.font_families == ("Inter",)


def test_en_locale_keeps_ascii_digits(tmp_path: Path) -> None:
    _, label = _label(tmp_path, "en")
    assert "17" in label.text  # no overlay, no digit mapping


def test_undeclared_locale_is_error(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    template.write_text(_TPL, encoding="utf-8")
    result = Compiler().compile(template, None, "square", "de", None)
    assert any(d.code == "ARC-TPL-100" for d in result.diagnostics)


def test_sibling_data_file_overlay(tmp_path: Path) -> None:
    """--data base.yaml --locale fa auto-applies base.fa.yaml if present (reported inferred)."""
    template = tmp_path / "t.yaml"
    template.write_text(_TPL, encoding="utf-8")
    (tmp_path / "d.yaml").write_text("hour: 8\n", encoding="utf-8")
    (tmp_path / "d.fa.yaml").write_text("hour: 21\n", encoding="utf-8")
    result = Compiler().compile(template, tmp_path / "d.yaml", "square", "fa", None)
    assert result.document is not None, result.diagnostics
    label = result.document.root.children[0]
    assert "۲۱" in label.text  # sibling overlay hour=21, fa digits
    assert result.inferred.get("data_overlay") == "d.fa.yaml"


def test_four_layer_data_precedence(tmp_path: Path) -> None:
    """RR2-1 / ADR-0002 D3: preview < locales.<L>.data < user base --data < user sidecar.

    User data always outranks template data; the sidecar outranks the base file. Each
    variable below is set at a different highest layer so the winner proves the order.
    """
    template = tmp_path / "t.yaml"
    template.write_text(_TPL, encoding="utf-8")
    # hour set at every layer; base wins over inline locale data, sidecar wins over base.
    (tmp_path / "d.yaml").write_text("hour: 8\n", encoding="utf-8")
    result = Compiler().compile(template, tmp_path / "d.yaml", "square", "fa", None)
    assert result.document is not None, result.diagnostics
    label = result.document.root.children[0]
    # No sidecar: user base (8) must beat inline locale data (19).
    assert "۸" in label.text and "۱۹" not in label.text
    # Inline overlay application is reported as an inference (RR2-3).
    assert result.inferred.get("locale_data") == "locales.fa.data"
    # With a sidecar, it outranks the base file.
    (tmp_path / "d.fa.yaml").write_text("hour: 21\n", encoding="utf-8")
    result2 = Compiler().compile(template, tmp_path / "d.yaml", "square", "fa", None)
    assert result2.document is not None, result2.diagnostics
    assert "۲۱" in result2.document.root.children[0].text
    # Without user data at all, inline locale data (19) beats preview_data (17).
    result3 = Compiler().compile(template, None, "square", "fa", None)
    assert result3.document is not None, result3.diagnostics
    assert "۱۹" in result3.document.root.children[0].text

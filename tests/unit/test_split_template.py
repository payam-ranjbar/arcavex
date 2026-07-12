"""Split-template loading tests: equivalence, duplicate sections, and same semantics."""

from __future__ import annotations

from pathlib import Path

from arcavex.kernel.ir.canonical import canonical_hash
from arcavex.services.template.compiler import Compiler

_ONE_FILE = """\
version: 0.1.0
variables:
  title: {type: string, required: true}
formats:
  square: {canvas: {width: 400px, height: 400px, dpi: 96}}
preview_data:
  title: "Hi"
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "{{ title }}"
      style: {font: Inter, font_size: 24px, color: white}
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 80%, h: fit_content}
"""


def _compile_hash(template: Path) -> str:
    doc = Compiler().compile(template, None, "square", None, None).document
    assert doc is not None
    return canonical_hash(doc.canonical_dict())


def test_split_and_one_file_are_equivalent(tmp_path: Path) -> None:
    one = tmp_path / "one"
    one.mkdir()
    (one / "template.yaml").write_text(_ONE_FILE, encoding="utf-8")

    split = tmp_path / "split"
    split.mkdir()
    (split / "template.yaml").write_text(
        """\
version: 0.1.0
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "{{ title }}"
      style: {font: Inter, font_size: 24px, color: white}
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 80%, h: fit_content}
""",
        encoding="utf-8",
    )
    (split / "schema.yaml").write_text("title: {type: string, required: true}\n", encoding="utf-8")
    (split / "formats.yaml").write_text(
        "square: {canvas: {width: 400px, height: 400px, dpi: 96}}\n", encoding="utf-8"
    )
    (split / "preview-data.yaml").write_text('title: "Hi"\n', encoding="utf-8")

    assert _compile_hash(one) == _compile_hash(split)


def test_passing_directory_or_template_yaml_equivalent(tmp_path: Path) -> None:
    d = tmp_path / "tpl"
    d.mkdir()
    (d / "template.yaml").write_text(_ONE_FILE, encoding="utf-8")
    assert _compile_hash(d) == _compile_hash(d / "template.yaml")


def test_duplicate_inline_and_split_section_is_error(tmp_path: Path) -> None:
    d = tmp_path / "dup"
    d.mkdir()
    (d / "template.yaml").write_text(_ONE_FILE, encoding="utf-8")  # has inline formats
    (d / "formats.yaml").write_text(
        "square: {canvas: {width: 400px, height: 400px, dpi: 96}}\n", encoding="utf-8"
    )
    result = Compiler().compile(d, None, "square", None, None)
    assert result.document is None
    assert any(d.code == "ARC-TPL-097" for d in result.diagnostics)


def test_split_variable_diagnostic_points_at_schema_file(tmp_path: Path) -> None:
    """A variable error in a split template locates the sidecar file, not template.yaml."""
    d = tmp_path / "s"
    d.mkdir()
    (d / "template.yaml").write_text(
        """\
version: 0.1.0
root: {type: group, id: root, children: []}
""",
        encoding="utf-8",
    )
    (d / "schema.yaml").write_text("count: {type: number, required: true}\n", encoding="utf-8")
    (d / "formats.yaml").write_text(
        "square: {canvas: {width: 100px, height: 100px, dpi: 96}}\n", encoding="utf-8"
    )
    data = d / "data.yaml"
    data.write_text("other: 1\n", encoding="utf-8")
    result = Compiler().compile(d, data, "square", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-014")
    assert diag.source is not None
    assert diag.source.file is not None and diag.source.file.endswith("schema.yaml")

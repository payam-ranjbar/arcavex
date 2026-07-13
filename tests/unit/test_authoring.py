"""Authoring service tests: template new renders, inspect golden, split preserves semantics."""

from __future__ import annotations

from pathlib import Path

from arcavex.bootstrap import build_facade
from arcavex.kernel.ir.canonical import canonical_hash
from arcavex.services.template.compiler import Compiler


def test_scaffold_renders_out_of_the_box(tmp_path: Path) -> None:
    facade = build_facade()
    target = tmp_path / "my-card"
    scaffold = facade.scaffold_template("my-card", target)
    assert scaffold.ok
    assert set(scaffold.files) == {"template.yaml", "data.yaml", "README.md"}
    out = tmp_path / "card.png"
    result = facade.render_file(target, None, scaffold.format, output=out)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert out.is_file()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_scaffold_refuses_existing_nonempty(tmp_path: Path) -> None:
    facade = build_facade()
    target = tmp_path / "exists"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    result = facade.scaffold_template("exists", target)
    assert not result.ok
    assert any(d.code == "ARC-TPL-070" for d in result.diagnostics)


def test_inspect_reports_contract(tmp_path: Path) -> None:
    facade = build_facade()
    report = facade.inspect_template(Path("examples/hello-poster"))
    assert report.ok
    var_names = {v.name for v in report.variables}
    assert var_names == {"title", "subtitle"}
    title = next(v for v in report.variables if v.name == "title")
    assert title.type == "string" and title.required is True and title.doc
    assert {f.name for f in report.formats} == {"square", "story"}
    assert "title" in {n.id for n in report.nodes}
    fn_names = {f.name for f in report.functions}
    assert "contrast_color" in fn_names and "locale_digits" in fn_names
    assert report.preview_data.get("title")


def test_split_preserves_semantics(tmp_path: Path) -> None:
    facade = build_facade()
    target = tmp_path / "card"
    facade.scaffold_template("card", target)
    before = Compiler().compile(target, None, "square", None, None).document
    assert before is not None
    before_hash = canonical_hash(before.canonical_dict())

    split = facade.split_template(target)
    assert split.ok
    assert (target / "schema.yaml").is_file()
    assert (target / "formats.yaml").is_file()

    after = Compiler().compile(target, None, "square", None, None).document
    assert after is not None
    assert canonical_hash(after.canonical_dict()) == before_hash


def test_split_refuses_when_already_split(tmp_path: Path) -> None:
    facade = build_facade()
    target = tmp_path / "card"
    facade.scaffold_template("card", target)
    assert facade.split_template(target).ok
    second = facade.split_template(target)
    assert not second.ok
    assert any(d.code == "ARC-TPL-071" for d in second.diagnostics)

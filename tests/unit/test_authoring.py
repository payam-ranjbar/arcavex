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
    report = facade.inspect_template(Path("tests/fixtures/basic-poster"))
    assert report.ok
    var_names = {v.name for v in report.variables}
    assert var_names == {"title", "subtitle", "day", "time"}
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


def test_scaffold_readme_is_transport_neutral(tmp_path: Path) -> None:
    """Each step names the CLI command and the MCP tool; the guide it points at is served."""
    facade = build_facade()
    target = tmp_path / "card"
    assert facade.scaffold_template("card", target).ok
    readme = (target / "README.md").read_text(encoding="utf-8")
    for tool in (
        "arcavex_render",
        "arcavex_render_preview",
        "arcavex_template_inspect",
        "arcavex_template_patch",
        "arcavex_template_validate",
        "arcavex_layout_inspect",
        "arcavex_data_set",
        "arcavex_diagnostic_explain",
        "arcavex_shape_list",
    ):
        assert tool in readme, tool
    assert "skill://arcavex-design-studio/SKILL.md" in readme
    assert "project README" not in readme
    assert "arcavex template patch card --set nodes.title.style.color" in readme
    assert '"width": "297mm"' in readme  # the print-format example is real JSON
    assert "TITLE GOES HERE" in readme and "ARC-PRJ-015" in readme
    template = (target / "template.yaml").read_text(encoding="utf-8")
    assert "Phase 2" not in template and "template README" not in template

"""``template new --format``: the scaffold declares canvases from the preset table.

The scaffold used to ship square + story only, so a print poster meant hand-writing a canvas
before the first render. These tests pin the preset table, the scaffold that reads it, the
located refusal for an unknown name, and the docs table that quotes it.
"""

from __future__ import annotations

import re
from pathlib import Path

from arcavex.bootstrap import build_facade
from arcavex.services.template.loader import load_yaml
from arcavex.services.template.presets import (
    DEFAULT_SCAFFOLD_FORMATS,
    FORMAT_PRESETS,
    preset_names,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TICKED = re.compile(r"`([^`]+)`")


def test_the_default_scaffold_still_declares_square_and_story(tmp_path: Path) -> None:
    facade = build_facade()
    result = facade.scaffold_template("card", tmp_path / "card")
    assert result.ok
    assert result.formats == list(DEFAULT_SCAFFOLD_FORMATS) and result.format == "square"
    raw = load_yaml(tmp_path / "card" / "template.yaml")
    assert list(raw["formats"]) == ["square", "story"]


def test_a_print_preset_is_declared_and_renders(tmp_path: Path) -> None:
    facade = build_facade()
    target = tmp_path / "poster"
    result = facade.scaffold_template("poster", target, formats=["a4", "square"])
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert result.formats == ["a4", "square"] and result.format == "a4"

    raw = load_yaml(target / "template.yaml")
    assert raw["formats"]["a4"]["canvas"] == FORMAT_PRESETS["a4"].canvas()
    assert raw["formats"]["a4"]["canvas"]["bleed"] == "3mm"
    inspected = facade.inspect_template(target)
    a4 = next(f for f in inspected.formats if f.name == "a4")
    assert (a4.width, a4.height, a4.dpi) == ("210mm", "297mm", 300)

    # Rendered at 72 dpi to keep the test quick; the canvas is still A4.
    out = tmp_path / "a4.png"
    rendered = facade.render_file(target, None, "a4", output=out, dpi=72)
    assert rendered.ok, [d.model_dump() for d in rendered.diagnostics]
    assert out.is_file()


def test_every_preset_scaffolds_a_template_that_validates(tmp_path: Path) -> None:
    facade = build_facade()
    target = tmp_path / "all"
    result = facade.scaffold_template("all", target, formats=list(FORMAT_PRESETS))
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    for name in FORMAT_PRESETS:
        checked = facade.check_template(target, format_name=name)
        assert checked.ok, (name, [d.model_dump() for d in checked.diagnostics])


def test_an_unknown_preset_is_a_located_refusal_that_lists_the_presets(tmp_path: Path) -> None:
    facade = build_facade()
    target = tmp_path / "nope"
    result = facade.scaffold_template("nope", target, formats=["a4", "postcard"])
    assert not result.ok
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-072")
    assert "postcard" in diag.message
    assert diag.hint is not None
    for name in FORMAT_PRESETS:
        assert name in diag.hint
    assert not target.exists()  # nothing half-written


def test_preset_names_are_lowercase_identifiers() -> None:
    """A preset name is also the format name a template declares, so it must be a plain key."""
    for name in FORMAT_PRESETS:
        assert re.fullmatch(r"[a-z][a-z0-9]*", name), name
    assert preset_names().split(", ") == list(FORMAT_PRESETS)


def _table_rows(text: str, heading: str) -> list[list[str]]:
    lines = text.splitlines()
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("#")), len(lines))
    rows: list[list[str]] = []
    for line in lines[start:end]:
        if not line.startswith("|") or set(line) <= {"|", "-", " "}:
            continue
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def test_template_schema_docs_tabulate_the_presets() -> None:
    """The ``formats`` section quotes every preset with the canvas the scaffold writes."""
    text = (_REPO_ROOT / "docs" / "template-schema.md").read_text(encoding="utf-8")
    documented: dict[str, list[str]] = {}
    for row in _table_rows(text, "### `formats`"):
        names = _TICKED.findall(row[0])
        if len(names) == 1 and names[0] in FORMAT_PRESETS:
            documented[names[0]] = row
    assert set(documented) == set(FORMAT_PRESETS), sorted(
        set(FORMAT_PRESETS) ^ set(documented)
    )
    for name, preset in FORMAT_PRESETS.items():
        canvas_cell = documented[name][1]
        for value in (preset.width, preset.height, str(preset.dpi)):
            assert value in canvas_cell, (name, canvas_cell)
        if preset.bleed is not None:
            assert preset.bleed in canvas_cell, (name, canvas_cell)


def test_cli_docs_name_every_preset() -> None:
    text = (_REPO_ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    for name in FORMAT_PRESETS:
        assert f"`{name}`" in text, name

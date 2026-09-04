"""Template-schema doc drift: the style, paragraph, and shape-generator tables track the code.

docs/template-schema.md is the authoring reference, and its Nodes section tabulates the
``style:`` vocabulary, the ``paragraph:`` keys, and every shape generator's parameters. Those
facts live in code — the compiler's whitelists, the IR's ``Literal`` value sets, and the
generators' pydantic schemas — so a key or parameter added or removed there without a matching
table row must fail here rather than leave an author (or an LLM) reading source to learn it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from pydantic_core import PydanticUndefined

from arcavex.builtin.shapes_core import builtin_shapes
from arcavex.kernel.ir.models import ParagraphSpec, Style

# The key sets are private to the compiler by convention (they are its validation whitelists),
# but they are the only source of truth for what an author may write in a ``style:``,
# ``paragraph:``, or run mapping. Importing them means the doc is checked against the engine's
# own vocabulary rather than a second copy in this test that could drift the same way.
from arcavex.services.template.compiler import _PARAGRAPH_KEYS, _RUN_KEYS, _STYLE_KEYS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "docs" / "template-schema.md"
_TICKED = re.compile(r"`([^`]+)`")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")  # a pipe not escaped as ``\|`` inside a cell


def _section(heading: str) -> str:
    """The body of the ``### <heading>`` section: its text up to the next heading of any level."""
    lines = _DOC.read_text(encoding="utf-8").splitlines()
    assert f"### {heading}" in lines, f"docs/template-schema.md has no '### {heading}' section"
    start = lines.index(f"### {heading}") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("#")), len(lines))
    return "\n".join(lines[start:end])


def _table_rows(section: str) -> list[list[str]]:
    """Every markdown table row in ``section`` (header rows included) as stripped cells."""
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|") or set(line) <= {"|", "-", " "}:
            continue
        rows.append([cell.strip() for cell in _CELL_SPLIT.split(line.strip().strip("|"))])
    return rows


def _first_cell_keys(section: str) -> set[str]:
    return {key for row in _table_rows(section) for key in _TICKED.findall(row[0])}


def _row(section: str, key: str) -> list[str]:
    matches = [row for row in _table_rows(section) if _TICKED.findall(row[0]) == [key]]
    assert len(matches) == 1, f"expected exactly one table row for `{key}`, found {len(matches)}"
    return matches[0]


def _literal_values(model: type, field: str) -> set[str]:
    return set(get_args(model.model_fields[field].annotation))


def _format_default(default: object) -> str | None:
    """Render a schema default the way the doc's Default column writes it (``16.0`` -> ``16``)."""
    if default is PydanticUndefined:
        return None
    if isinstance(default, float) and default.is_integer():
        return str(int(default))
    return str(default)


# --------------------------------------------------------------------------------- style keys
def test_style_table_rows_are_exactly_the_compiler_vocabulary() -> None:
    """Each ``_STYLE_KEYS`` entry has a row, and no row names a key the compiler rejects."""
    documented = _first_cell_keys(_section("`style` keys"))
    assert documented == set(_STYLE_KEYS), (
        f"missing rows: {sorted(set(_STYLE_KEYS) - documented)}; "
        f"stale rows: {sorted(documented - set(_STYLE_KEYS))}"
    )


def test_style_enumerated_values_match_the_ir() -> None:
    """The align/direction rows list every value the IR ``Literal`` accepts, and nothing else."""
    section = _section("`style` keys")
    for key in ("align", "direction"):
        listed = set(_TICKED.findall(_row(section, key)[2]))
        assert listed == _literal_values(Style, key), f"style.{key} values drifted: {listed}"


def test_run_override_keys_are_listed() -> None:
    """The ``runs:`` note under the style table names every per-run override key."""
    section = _section("`style` keys")
    missing = sorted(key for key in _RUN_KEYS if f"`{key}`" not in section)
    assert not missing, f"run keys not mentioned in the `style` keys section: {missing}"


# ----------------------------------------------------------------------------- paragraph keys
def test_paragraph_table_rows_are_exactly_the_compiler_vocabulary() -> None:
    documented = _first_cell_keys(_section("`paragraph`"))
    assert documented == set(_PARAGRAPH_KEYS), (
        f"missing rows: {sorted(set(_PARAGRAPH_KEYS) - documented)}; "
        f"stale rows: {sorted(documented - set(_PARAGRAPH_KEYS))}"
    )


def test_paragraph_enumerated_values_match_the_ir() -> None:
    section = _section("`paragraph`")
    for key in _PARAGRAPH_KEYS:
        listed = set(_TICKED.findall(_row(section, key)[1]))
        assert listed == _literal_values(ParagraphSpec, key), (
            f"paragraph.{key} values drifted: {listed}"
        )


def test_paragraph_align_is_documented_as_primary_with_style_fallback() -> None:
    """The compiler reads ``paragraph.align`` first and falls back to ``style.align``."""
    section = _section("`paragraph`")
    assert "primary" in section and "fallback" in section
    assert "`style.align`" in _row(section, "align")[2]


# ---------------------------------------------------------------------------- shape generators
def test_shape_generator_table_matches_the_registry() -> None:
    """Every built-in generator and each of its schema fields has a row; no row is stale."""
    documented: dict[str, dict[str, list[str]]] = {}
    for row in _table_rows(_section("Shape generator parameters")):
        generators = _TICKED.findall(row[0])
        params = _TICKED.findall(row[1]) if len(row) > 1 else []
        if len(generators) == 1 and len(params) == 1:
            documented.setdefault(generators[0], {})[params[0]] = row

    expected = {gen.name: set(gen.param_schema.model_fields) for gen in builtin_shapes()}
    assert set(documented) == set(expected), (
        f"missing generators: {sorted(set(expected) - set(documented))}; "
        f"stale generators: {sorted(set(documented) - set(expected))}"
    )
    for name, params in expected.items():
        assert set(documented[name]) == params, (
            f"{name}: missing params {sorted(params - set(documented[name]))}; "
            f"stale params {sorted(set(documented[name]) - params)}"
        )


def test_shape_generator_defaults_match_the_schemas() -> None:
    """The Default column quotes each schema default, or says ``required`` when there is none."""
    rows = {
        (_TICKED.findall(row[0])[0], _TICKED.findall(row[1])[0]): row
        for row in _table_rows(_section("Shape generator parameters"))
        if len(row) >= 4 and _TICKED.findall(row[0]) and _TICKED.findall(row[1])
    }
    for gen in builtin_shapes():
        for param, field in gen.param_schema.model_fields.items():
            default_cell = rows[(gen.name, param)][3]
            rendered = _format_default(field.default)
            if rendered is None:
                assert default_cell == "required", f"{gen.name}.{param}: {default_cell!r}"
            else:
                assert f"`{rendered}`" in default_cell, (
                    f"{gen.name}.{param}: doc says {default_cell!r}, schema default is {rendered}"
                )

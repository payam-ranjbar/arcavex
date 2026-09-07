"""The skill's editor-command table must name the fields the contract actually declares.

The skill teaches an assistant the shape of a semantic transaction, and an assistant that follows
it composes commands from that table. Its `splice_children` row said `layer_id, children`; the
command takes `parent_id`, `index`, `remove_count` and `entries`, so anyone who trusted the table
was refused. The drift test beside this one checks tool names, command paths and diagnostic codes
-- not the fields inside a command -- so nothing caught it.
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

from arcavex.kernel.editor import SemanticTransaction

SKILL = Path(__file__).resolve().parents[2] / "skills" / "arcavex-design-studio"
REFERENCE = SKILL / "references" / "engine-and-loop.md"
#: A row of the skill's command table: the kind, then everything it says about that kind.
_ROW = re.compile(r"^(?P<kind>[a-z_]+) {2,}(?P<rest>.+)$", re.MULTILINE)


def _fields_in(rest: str) -> set[str]:
    """The field names a table row lists, ignoring its trailing parenthetical note.

    Rows separate fields with commas and, where a command takes either of two, with "and/or".
    """
    listed = rest.split("(", 1)[0]
    return {
        token.strip()
        for token in listed.replace(" and/or ", ", ").split(",")
        if token.strip() and re.fullmatch(r"[a-z_]+", token.strip())
    }


def _declared_fields() -> dict[str, set[str]]:
    """Every command kind mapped to the field names its model declares, from the contract."""
    annotated = typing.get_args(SemanticTransaction.model_fields["commands"].annotation)[0]
    union = typing.get_args(annotated)[0]
    out: dict[str, set[str]] = {}
    for member in typing.get_args(union):
        literals = typing.get_args(member.model_fields["kind"].annotation)
        out[literals[0]] = {name for name in member.model_fields if name != "kind"}
    return out


def _table_rows() -> dict[str, set[str]]:
    """Every command row of the skill's table, mapped to the fields it names."""
    text = REFERENCE.read_text(encoding="utf-8")
    kinds = _declared_fields()
    return {
        match["kind"]: _fields_in(match["rest"])
        for match in _ROW.finditer(text)
        if match["kind"] in kinds
    }


def test_the_skill_documents_every_command_kind() -> None:
    missing = sorted(set(_declared_fields()) - set(_table_rows()))
    assert not missing, f"the skill's command table omits: {missing}"


@pytest.mark.parametrize("kind", sorted(_declared_fields()))
def test_each_row_names_only_fields_the_command_has(kind: str) -> None:
    """A field the command does not declare is a refusal for anyone who follows the table."""
    rows = _table_rows()
    if kind not in rows:  # the omission is its own test
        pytest.skip(f"{kind} is not in the table")

    invented = sorted(rows[kind] - _declared_fields()[kind])

    assert not invented, (
        f"the skill says `{kind}` takes {invented}, which the command does not declare; "
        f"it takes {sorted(_declared_fields()[kind])}"
    )


def test_the_required_fields_of_each_command_are_all_named() -> None:
    """Naming only some required fields sends an assistant into an avoidable refusal."""
    annotated = typing.get_args(SemanticTransaction.model_fields["commands"].annotation)[0]
    union = typing.get_args(annotated)[0]
    rows = _table_rows()
    gaps: list[str] = []
    for member in typing.get_args(union):
        kind = typing.get_args(member.model_fields["kind"].annotation)[0]
        required = {
            name
            for name, field in member.model_fields.items()
            if name != "kind" and field.is_required()
        }
        if kind in rows:
            missing = sorted(required - rows[kind])
            if missing:
                gaps.append(f"{kind}: {missing}")
    assert not gaps, f"the skill's table omits required fields: {gaps}"

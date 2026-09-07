"""Editor contract tests: the shape every semantic mutation must take to be executable.

Phase 1 queued proposals as an untyped `command_payload` dict because nothing executed them yet.
Phase 2 executes them, so the payload becomes a discriminated union that is validated at the
boundary rather than interpreted deep inside a service. These tests fix the parts a caller — the
desktop, an AI client, or the CLI — can rely on: which kinds exist, what each carries, and what a
report hands back.

The strictness here is deliberate. A mutation that reaches the filesystem with a misspelled key, a
non-canonical project path, or a NaN offset is a corrupted project, and the point of a typed
envelope is that none of those get that far.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from arcavex.kernel.editor import (
    Actor,
    ChangedPath,
    ConflictDetail,
    EditorTarget,
    HistoryEntry,
    HistoryReport,
    SemanticTransaction,
    TransactionReport,
    parse_command,
)

_REVISION = "a1" * 32
_OTHER_REVISION = "b2" * 32
_COMMAND_ID = "9f2c1d7e-4b3a-4c58-9e21-0d7a6f5b8c34"


def _project_path() -> str:
    """A canonical absolute path this platform agrees with, since the models require one."""
    return str(Path(Path(__file__).anchor) / "arcavex-contract-project")


def _transaction(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command_id": _COMMAND_ID,
        "project_path": _project_path(),
        "base_project_revision": _REVISION,
        "actor": {"id": "desktop", "display_name": "Arcavex Desktop"},
        "target": {"format": "square", "locale": "en"},
        "commands": [{"kind": "set_text", "layer_id": "title", "text": "New headline"}],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------------- command kinds

# One representative payload per kind. The plan fixes this list, and a kind that cannot round-trip
# is a kind the desktop cannot send.
_COMMANDS: list[dict[str, Any]] = [
    {"kind": "set_text", "layer_id": "title", "text": "New headline"},
    {"kind": "set_property", "layer_id": "title", "keypath": "style.font_size", "value": "48pt"},
    {"kind": "set_visibility", "layer_id": "badge", "visible": False},
    {"kind": "translate", "layer_ids": ["title", "subtitle"], "dx_pt": 12.5, "dy_pt": -4.0},
    {"kind": "resize", "layer_id": "photo", "w_pt": 320.0, "h_pt": 240.0},
    {"kind": "rotate", "layer_id": "badge", "degrees": 15.0},
    {"kind": "reorder", "layer_id": "badge", "parent_id": "root", "index": 2},
    {"kind": "reparent", "layer_id": "badge", "parent_id": "header", "index": 0},
    {"kind": "duplicate", "layer_id": "badge"},
    {"kind": "delete", "layer_ids": ["badge"]},
    {"kind": "group", "layer_ids": ["title", "subtitle"], "group_id": "headline"},
    {"kind": "set_display_name", "layer_id": "title", "display_name": "Headline"},
    {
        "kind": "set_effects",
        "layer_id": "photo",
        "effects": [{"name": "halftone", "params": {"dot_pt": 2.0}}],
    },
    # Engine-authored: the restoring inverse of delete and group. Clients rarely compose one,
    # but it round-trips like every other kind because undo re-submits it.
    {
        "kind": "splice_children",
        "parent_id": "root",
        "index": 2,
        "remove_count": 0,
        "entries": [{"id": "badge", "type": "shape"}],
    },
]


@pytest.mark.parametrize("payload", _COMMANDS, ids=lambda payload: str(payload["kind"]))
def test_every_command_kind_round_trips_through_json(payload: dict[str, Any]) -> None:
    """A command survives the trip to an MCP client and back unchanged."""
    command = parse_command(payload)

    restored = parse_command(json.loads(command.model_dump_json()))

    assert restored == command
    assert restored.kind == payload["kind"]


def test_the_plan_s_command_vocabulary_is_complete() -> None:
    """Guard against a kind being added to the union but never exercised here."""
    from arcavex.kernel.editor import COMMAND_KINDS

    assert {payload["kind"] for payload in _COMMANDS} == set(COMMAND_KINDS)


def test_an_unknown_kind_is_rejected_rather_than_ignored() -> None:
    with pytest.raises(ValidationError):
        parse_command({"kind": "set_gradient", "layer_id": "title"})


def test_an_unknown_key_is_rejected_rather_than_dropped() -> None:
    """A misspelled field must fail loudly; silently dropping it would edit the wrong thing."""
    with pytest.raises(ValidationError):
        parse_command({"kind": "set_text", "layer_id": "title", "txt": "typo"})


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_geometry_must_be_finite(bad: float) -> None:
    with pytest.raises(ValidationError):
        parse_command({"kind": "translate", "layer_ids": ["title"], "dx_pt": bad, "dy_pt": 0.0})


def test_resize_refuses_a_non_positive_extent() -> None:
    """A zero or negative box is not a resize; it is a delete with a confusing name."""
    for width in (0.0, -10.0):
        with pytest.raises(ValidationError):
            parse_command({"kind": "resize", "layer_id": "photo", "w_pt": width, "h_pt": 10.0})


def test_a_command_naming_no_layer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_command({"kind": "delete", "layer_ids": []})


# ---------------------------------------------------------------------------------- the envelope


def test_a_transaction_carries_everything_needed_to_execute_it_safely() -> None:
    transaction = SemanticTransaction.model_validate(_transaction())

    assert str(transaction.command_id) == _COMMAND_ID
    assert transaction.base_project_revision == _REVISION
    assert transaction.actor == Actor(id="desktop", display_name="Arcavex Desktop")
    assert transaction.target == EditorTarget(format="square", locale="en")
    assert transaction.commands[0].kind == "set_text"


def test_a_transaction_needs_at_least_one_command() -> None:
    with pytest.raises(ValidationError):
        SemanticTransaction.model_validate(_transaction(commands=[]))


def test_a_transaction_rejects_a_relative_project_path() -> None:
    """The engine locks and snapshots by canonical path; a relative one addresses nothing."""
    with pytest.raises(ValidationError):
        SemanticTransaction.model_validate(_transaction(project_path="poster"))


def test_a_transaction_rejects_a_revision_that_is_not_a_digest() -> None:
    with pytest.raises(ValidationError):
        SemanticTransaction.model_validate(_transaction(base_project_revision="head"))


def test_a_transaction_rejects_a_command_id_that_is_not_a_uuid() -> None:
    with pytest.raises(ValidationError):
        SemanticTransaction.model_validate(_transaction(command_id="latest"))


def test_multiple_commands_travel_as_one_transaction() -> None:
    """Multi-selection and grouping are one undo step, so they must be one transaction."""
    transaction = SemanticTransaction.model_validate(
        _transaction(
            commands=[
                {"kind": "translate", "layer_ids": ["a", "b"], "dx_pt": 4.0, "dy_pt": 0.0},
                {"kind": "set_visibility", "layer_id": "c", "visible": True},
            ]
        )
    )

    assert [command.kind for command in transaction.commands] == ["translate", "set_visibility"]


# ----------------------------------------------------------------------------------- the reports


def test_a_successful_report_returns_the_inverse_that_undoes_it() -> None:
    """Undo replays engine-authored inverses; a report without one cannot be undone."""
    report = TransactionReport.model_validate(
        {
            "ok": True,
            "command_id": _COMMAND_ID,
            "canonical_path": _project_path(),
            "project_revision": _OTHER_REVISION,
            "render_revision": _REVISION,
            "changed": [{"path": "template.yaml", "change": "modified"}],
            "changed_layer_ids": ["title"],
            "inverse": _transaction(
                command_id="0a3f6b21-5c7d-4e9a-8b12-3f4d5e6a7b8c",
                base_project_revision=_OTHER_REVISION,
                commands=[{"kind": "set_text", "layer_id": "title", "text": "Old headline"}],
            ),
        }
    )

    assert report.ok is True
    assert report.inverse is not None
    assert report.inverse.commands[0].kind == "set_text"
    assert report.changed[0] == ChangedPath(path="template.yaml", change="modified")
    assert report.conflict is None


def test_a_conflict_names_the_files_and_layers_that_disagree() -> None:
    """"Someone else changed it" is not actionable; the caller needs to see what and where."""
    report = TransactionReport.model_validate(
        {
            "ok": False,
            "command_id": _COMMAND_ID,
            "canonical_path": _project_path(),
            "conflict": {
                "expected_project_revision": _REVISION,
                "actual_project_revision": _OTHER_REVISION,
                "changed": [{"path": "data/event.yaml", "change": "modified"}],
                "layer_ids": ["title"],
            },
        }
    )

    assert report.ok is False
    assert report.inverse is None
    assert report.conflict is not None
    assert report.conflict.actual_project_revision == _OTHER_REVISION
    assert report.conflict.changed[0].path == "data/event.yaml"


def test_history_reports_what_can_be_undone_and_redone() -> None:
    entry = {
        "command_id": _COMMAND_ID,
        "actor": {"id": "ai", "display_name": "Claude"},
        "summary": "Set text of 'title'",
        "before_project_revision": _REVISION,
        "after_project_revision": _OTHER_REVISION,
        "created_at": "2026-01-02T03:04:05.678901Z",
    }

    report = HistoryReport.model_validate(
        {
            "ok": True,
            "canonical_path": _project_path(),
            "entries": [entry],
            "can_undo": True,
            "can_redo": False,
            "branched_by_external_edit": True,
        }
    )

    assert report.entries == [HistoryEntry.model_validate(entry)]
    assert report.can_undo is True
    # An external edit ends the redo line rather than replaying across someone else's work.
    assert report.can_redo is False
    assert report.branched_by_external_edit is True


def test_a_conflict_detail_is_complete_enough_to_render_on_its_own() -> None:
    detail = ConflictDetail.model_validate(
        {
            "expected_project_revision": _REVISION,
            "actual_project_revision": _OTHER_REVISION,
            "changed": [],
            "layer_ids": [],
        }
    )

    assert detail.expected_project_revision != detail.actual_project_revision


def test_a_project_path_is_canonicalised_rather_than_refused() -> None:
    """Forward slashes are how every other tool on this surface takes a Windows path.

    `project_path` compared the string it was given against the resolved one and refused any
    difference, so `C:/Users/x/post` -- which resolves to exactly the same directory -- was
    rejected as "not canonical" while `project_snapshot`, `layer_tree` and `project_preview`
    all accepted it. Two agents lost round trips to that inconsistency, and the message never
    said what was wrong with the path.
    """
    import os
    from pathlib import Path

    from arcavex.kernel.editor import SemanticTransaction

    root = Path(os.getcwd()).resolve()
    slashed = root.as_posix()

    transaction = SemanticTransaction.model_validate(
        {
            "command_id": "11111111-1111-4111-8111-111111111111",
            "project_path": slashed,
            "base_project_revision": "a" * 64,
            "actor": {"id": "test"},
            "commands": [{"kind": "set_text", "layer_id": "title", "text": "x"}],
        }
    )

    assert Path(transaction.project_path) == root


def test_a_relative_project_path_is_still_refused() -> None:
    """Canonicalising is not the same as accepting anything: a relative path is ambiguous."""
    import pytest
    from pydantic import ValidationError

    from arcavex.kernel.editor import SemanticTransaction

    with pytest.raises(ValidationError, match="absolute"):
        SemanticTransaction.model_validate(
            {
                "command_id": "11111111-1111-4111-8111-111111111111",
                "project_path": "some/relative/post",
                "base_project_revision": "a" * 64,
                "actor": {"id": "test"},
                "commands": [{"kind": "set_text", "layer_id": "title", "text": "x"}],
            }
        )

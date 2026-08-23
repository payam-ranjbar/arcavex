"""The undo/redo store: bounded, on disk, and honest about edits it did not make.

History lives under ``.arcavex/history/`` in the project itself, because the AI that edited over
MCP and the person at the desktop share one timeline — an in-memory stack in either process would
show each a fiction. The store records forward and inverse transactions with before/after
revisions, and the revision chain is what lets it detect an external edit and stop the redo line
instead of replaying over someone else's work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from arcavex.kernel.editor import SemanticTransaction
from arcavex.services.editor.history import HISTORY_LIMIT, HistoryStore

_REV = [f"{n:02x}" * 32 for n in range(1, 30)]


def _transaction(revision: str, text: str = "hello") -> SemanticTransaction:
    return SemanticTransaction.model_validate(
        {
            "command_id": "9f2c1d7e-4b3a-4c58-9e21-0d7a6f5b8c34",
            "project_path": str(Path(Path(__file__).anchor) / "arcavex-history-project"),
            "base_project_revision": revision,
            "actor": {"id": "test"},
            "commands": [{"kind": "set_text", "layer_id": "title", "text": text}],
        }
    )


def _record(store: HistoryStore, before: str, after: str, summary: str = "edit") -> None:
    store.record(
        forward=_transaction(before, text=f"forward-{after[:4]}"),
        inverse=_transaction(after, text=f"inverse-{before[:4]}"),
        before_project_revision=before,
        after_project_revision=after,
        summary=summary,
    )


@pytest.fixture()
def store(tmp_path: Path) -> HistoryStore:
    root = tmp_path / "project"
    root.mkdir()
    return HistoryStore(root)


def test_a_recorded_edit_becomes_undoable(store: HistoryStore) -> None:
    _record(store, _REV[0], _REV[1])

    state = store.state(current_revision=_REV[1])

    assert state.can_undo is True
    assert state.can_redo is False
    assert state.entries[-1].summary == "edit"


def test_undo_returns_the_inverse_and_moves_the_cursor(store: HistoryStore) -> None:
    _record(store, _REV[0], _REV[1])

    step = store.undo(current_revision=_REV[1])
    assert step is not None
    assert step.transaction.commands[0].text == f"inverse-{_REV[0][:4]}"  # type: ignore[union-attr]

    # After the engine applies the inverse the project is back at _REV[0]; redo is now available.
    store.mark_undone(step.entry.command_id, restored_revision=_REV[0])
    state = store.state(current_revision=_REV[0])
    assert state.can_undo is False
    assert state.can_redo is True


def test_redo_replays_the_forward_transaction(store: HistoryStore) -> None:
    _record(store, _REV[0], _REV[1])
    step = store.undo(current_revision=_REV[1])
    assert step is not None
    store.mark_undone(step.entry.command_id, restored_revision=_REV[0])

    redo = store.redo(current_revision=_REV[0])
    assert redo is not None
    assert redo.transaction.commands[0].text == f"forward-{_REV[1][:4]}"  # type: ignore[union-attr]

    store.mark_redone(redo.entry.command_id, restored_revision=_REV[1])
    state = store.state(current_revision=_REV[1])
    assert state.can_undo is True
    assert state.can_redo is False


def test_an_external_edit_ends_the_redo_line(store: HistoryStore) -> None:
    """Redo after someone else's edit would overwrite their work with ours."""
    _record(store, _REV[0], _REV[1])
    step = store.undo(current_revision=_REV[1])
    assert step is not None
    store.mark_undone(step.entry.command_id, restored_revision=_REV[0])

    # An external process changes the project: the current revision is now one history never saw.
    external = _REV[9]
    state = store.state(current_revision=external)

    assert state.can_redo is False
    assert state.branched_by_external_edit is True
    assert store.redo(current_revision=external) is None


def test_an_external_edit_also_blocks_undo_of_a_stale_entry(store: HistoryStore) -> None:
    """The last entry's after-revision no longer matches the project, so its inverse would be
    applied to a document it does not describe."""
    _record(store, _REV[0], _REV[1])

    state = store.state(current_revision=_REV[9])

    assert state.can_undo is False
    assert store.undo(current_revision=_REV[9]) is None
    assert state.branched_by_external_edit is True


def test_a_new_edit_after_undo_discards_the_redo_branch(store: HistoryStore) -> None:
    _record(store, _REV[0], _REV[1])
    step = store.undo(current_revision=_REV[1])
    assert step is not None
    store.mark_undone(step.entry.command_id, restored_revision=_REV[0])

    _record(store, _REV[0], _REV[2], summary="the new direction")

    state = store.state(current_revision=_REV[2])
    assert state.can_redo is False
    assert [entry.summary for entry in state.entries] == ["the new direction"]


def test_history_survives_a_process_restart(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    first = HistoryStore(root)
    _record(first, _REV[0], _REV[1])

    reopened = HistoryStore(root)
    state = reopened.state(current_revision=_REV[1])

    assert state.can_undo is True
    assert state.entries[-1].after_project_revision == _REV[1]


def test_history_is_bounded(store: HistoryStore) -> None:
    for index in range(HISTORY_LIMIT + 5):
        _record(store, _REV[index % 20], _REV[(index + 1) % 20], summary=f"edit {index}")

    state = store.state(current_revision=_REV[(HISTORY_LIMIT + 5) % 20])
    assert len(state.entries) == HISTORY_LIMIT
    assert state.entries[-1].summary == f"edit {HISTORY_LIMIT + 4}"


def test_a_corrupt_history_record_is_reported_not_fatal(
    store: HistoryStore, tmp_path: Path
) -> None:
    _record(store, _REV[0], _REV[1])
    history_dir = tmp_path / "project" / ".arcavex" / "history"
    (history_dir / "not-a-record.json").write_text("{malformed", encoding="utf-8")

    state = store.state(current_revision=_REV[1])

    assert state.can_undo is True, "the valid entry must survive its corrupt neighbour"
    assert any(d.code == "ARC-EDT-003" for d in state.diagnostics)


def test_records_hold_full_transactions_for_replay(store: HistoryStore) -> None:
    """The stored payloads are validated transactions, not free-form dicts."""
    _record(store, _REV[0], _REV[1])

    step = store.undo(current_revision=_REV[1])
    assert step is not None
    assert isinstance(step.transaction, SemanticTransaction)


def _summaries(entries: list[Any]) -> list[str]:
    return [entry.summary for entry in entries]


def test_a_write_outside_the_editor_leaves_the_history_findable(store: HistoryStore) -> None:
    """Editing a project's source another way branches the history; it does not delete it.

    `template_patch` and `data_set` write source files without going through the editor, which
    moves the project to a revision the chain has never seen. Undo then refuses, and an agent
    reported it as "ten entries of undo history destroyed with no warning".

    Nothing is destroyed: the records are still on disk, and `branched_by_external_edit` says
    exactly why the chain no longer applies. Pinned here so a future change cannot quietly turn
    a branch into a deletion.
    """
    _record(store, "a" * 64, "b" * 64, summary="set_text")

    # A patch lands out of band: the project sits at a revision the chain never produced.
    state = store.state(current_revision="c" * 64)

    assert state.entries, "the recorded entry is still on disk"
    assert state.branched_by_external_edit is True
    assert state.can_undo is False
    # And the same store still reports the entry as undoable once the project is back on chain.
    assert store.state(current_revision="b" * 64).can_undo is True

"""The project's undo/redo timeline: on disk, bounded, and honest about external edits.

History lives under ``.arcavex/history/`` in the project itself because the timeline belongs to
the project, not to a process. An AI editing over MCP and a person at the desktop share one
sequence of edits; an in-memory stack in either process would show each of them a fiction.

The store never applies anything. It hands back the transaction to replay — the engine-authored
inverse for undo, the recorded forward for redo — and the executor applies it like any other
mutation. The revision chain is what keeps this honest: an entry is only undoable while the
project is still at its ``after`` revision, and only redoable while the project is back at its
``before``. A revision history has never seen means someone else edited the project, and the
answer to "can I redo across that?" is no — replaying would overwrite their work.

Records are one JSON file per entry, named by sequence number, written atomically. A corrupt file
is reported as a diagnostic and skipped rather than poisoning the entries around it.

Each record also carries the exact bytes of every file the transaction changed, before and after.
The semantic inverse is the public contract a client can reason about, but replaying it cannot
promise byte-identity — YAML scalar style (quoting, flow vs block) does not survive a semantic
round trip — and undo/redo *must* return the project to the exact revision the chain recorded,
or the chain closes. So the engine's own undo restores bytes and keeps the inverse for reporting.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.kernel.editor import Actor, HistoryEntry, SemanticTransaction

#: Entries kept per project. Beyond this the oldest are dropped; an editing session that wants to
#: step back further than this has a project under version control for a reason.
HISTORY_LIMIT = 200

_RECORD_SUFFIX = ".json"


class _HistoryRecord(BaseModel):
    """One applied transaction as persisted: the entry plus both replay directions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    sequence: int = Field(ge=0)
    command_id: UUID
    actor: Actor
    summary: str
    before_project_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_project_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    forward: SemanticTransaction
    inverse: SemanticTransaction
    #: Exact bytes (base64) of each changed file before and after; ``None`` means absent.
    before_files: dict[str, str | None] = Field(default_factory=dict)
    after_files: dict[str, str | None] = Field(default_factory=dict)
    #: Where the cursor logically sits. "applied" entries are undo candidates newest-first;
    #: "undone" entries are redo candidates oldest-first.
    state: Literal["applied", "undone"] = "applied"

    def entry(self) -> HistoryEntry:
        return HistoryEntry(
            command_id=self.command_id,
            actor=self.actor,
            summary=self.summary,
            before_project_revision=self.before_project_revision,
            after_project_revision=self.after_project_revision,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class HistoryStep:
    """What the executor needs to perform one undo or redo."""

    entry: HistoryEntry
    transaction: SemanticTransaction
    #: Exact bytes to restore per project-relative path; ``None`` deletes the file.
    restore_files: dict[str, bytes | None] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoryState:
    """The timeline as a report-shaped snapshot."""

    entries: list[HistoryEntry]
    can_undo: bool
    can_redo: bool
    branched_by_external_edit: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)


class HistoryStore:
    """Reads and writes one project's history directory."""

    def __init__(self, root: Path) -> None:
        self._directory = root.resolve() / ".arcavex" / "history"

    # ---------------------------------------------------------------------------------- writing

    def record(
        self,
        *,
        forward: SemanticTransaction,
        inverse: SemanticTransaction,
        before_project_revision: str,
        after_project_revision: str,
        summary: str,
        before_files: dict[str, bytes | None] | None = None,
        after_files: dict[str, bytes | None] | None = None,
    ) -> None:
        """Append one applied transaction, discarding any redo branch it supersedes.

        A new edit after an undo makes the undone entries unreachable — redoing them would apply
        forwards recorded against a document that no longer exists — so they are deleted rather
        than kept as a trap.
        """
        records, _ = self._load()
        for record in records:
            if record.state == "undone":
                self._path(record.sequence).unlink(missing_ok=True)
        records = [record for record in records if record.state == "applied"]

        sequence = records[-1].sequence + 1 if records else 0
        self._write(
            _HistoryRecord(
                sequence=sequence,
                command_id=forward.command_id,
                actor=forward.actor,
                summary=summary,
                before_project_revision=before_project_revision,
                after_project_revision=after_project_revision,
                created_at=datetime.now(tz=UTC),
                forward=forward,
                inverse=inverse,
                before_files=_encode_files(before_files or {}),
                after_files=_encode_files(after_files or {}),
            )
        )

        # Bound the store by dropping the oldest applied entries.
        records, _ = self._load()
        applied = [record for record in records if record.state == "applied"]
        for stale in applied[: max(0, len(applied) - HISTORY_LIMIT)]:
            self._path(stale.sequence).unlink(missing_ok=True)

    def mark_undone(self, command_id: UUID, *, restored_revision: str) -> None:
        """Flip one entry to undone after its inverse was successfully applied."""
        del restored_revision  # the revision chain already encodes it; kept for call-site clarity
        self._flip(command_id, to_state="undone")

    def mark_redone(self, command_id: UUID, *, restored_revision: str) -> None:
        """Flip one entry back to applied after its forward was successfully replayed."""
        del restored_revision
        self._flip(command_id, to_state="applied")

    # ---------------------------------------------------------------------------------- reading

    def undo(self, *, current_revision: str) -> HistoryStep | None:
        """The inverse to apply, or ``None`` when nothing can be undone safely."""
        records, _ = self._load()
        applied = [record for record in records if record.state == "applied"]
        if not applied:
            return None
        candidate = applied[-1]
        if candidate.after_project_revision != current_revision:
            # The project is not where this entry left it: someone else edited it since.
            return None
        return HistoryStep(
            entry=candidate.entry(),
            transaction=candidate.inverse,
            restore_files=_decode_files(candidate.before_files),
        )

    def redo(self, *, current_revision: str) -> HistoryStep | None:
        """The forward to replay, or ``None`` when the redo line is closed."""
        records, _ = self._load()
        undone = [record for record in records if record.state == "undone"]
        if not undone:
            return None
        candidate = undone[0]
        if candidate.before_project_revision != current_revision:
            return None
        return HistoryStep(
            entry=candidate.entry(),
            transaction=candidate.forward,
            restore_files=_decode_files(candidate.after_files),
        )

    def state(self, *, current_revision: str) -> HistoryState:
        """The timeline as the desktop and MCP report it."""
        records, diagnostics = self._load()
        applied = [record for record in records if record.state == "applied"]
        undone = [record for record in records if record.state == "undone"]

        can_undo = bool(applied) and applied[-1].after_project_revision == current_revision
        can_redo = bool(undone) and undone[0].before_project_revision == current_revision

        # "Branched" means the chain and the project disagree: there is history, but the current
        # revision is not the one the relevant end of the chain expects.
        known_ends = {record.after_project_revision for record in applied[-1:]} | {
            record.before_project_revision for record in undone[:1]
        }
        branched = bool(records) and bool(known_ends) and current_revision not in known_ends

        return HistoryState(
            entries=[record.entry() for record in applied],
            can_undo=can_undo,
            can_redo=can_redo,
            branched_by_external_edit=branched,
            diagnostics=diagnostics,
        )

    # -------------------------------------------------------------------------------- internals

    def _path(self, sequence: int) -> Path:
        return self._directory / f"{sequence:08d}{_RECORD_SUFFIX}"

    def _write(self, record: _HistoryRecord) -> None:
        from arcavex.services.fsutil import atomic_write_bytes

        payload = record.model_dump_json(indent=2).encode("utf-8") + b"\n"
        atomic_write_bytes(self._path(record.sequence), payload)

    def _flip(self, command_id: UUID, *, to_state: Literal["applied", "undone"]) -> None:
        records, _ = self._load()
        for record in records:
            if record.command_id == command_id:
                self._write(record.model_copy(update={"state": to_state}))
                return

    def _load(self) -> tuple[list[_HistoryRecord], list[Diagnostic]]:
        if not self._directory.is_dir():
            return [], []
        records: list[_HistoryRecord] = []
        diagnostics: list[Diagnostic] = []
        for path in sorted(self._directory.glob(f"*{_RECORD_SUFFIX}")):
            try:
                records.append(
                    _HistoryRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
                )
            except (OSError, ValueError, ValidationError):
                diagnostics.append(
                    diagnostic(
                        "ARC-EDT-003",
                        "A history record could not be read and was skipped. Undo/redo of the "
                        "remaining entries still works.",
                        file=str(path),
                        hint="Remove the named file under .arcavex/history to clear this.",
                    )
                )
        records.sort(key=lambda record: record.sequence)
        return records, diagnostics


def _encode_files(files: dict[str, bytes | None]) -> dict[str, str | None]:
    return {
        path: None if content is None else base64.b64encode(content).decode("ascii")
        for path, content in files.items()
    }


def _decode_files(files: dict[str, str | None]) -> dict[str, bytes | None]:
    return {
        path: None if content is None else base64.b64decode(content)
        for path, content in files.items()
    }

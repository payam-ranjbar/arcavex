"""Atomic project-local proposal queue with revision-checked authorization."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from arcavex.kernel.api import (
    ProjectProposal,
    ProposalActionReport,
    ProposalActor,
    ProposalListReport,
)
from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic
from arcavex.services.fsutil import atomic_create_text, atomic_write_text
from arcavex.services.project_locking import (
    ensure_project_path_safe,
    project_mutation_lock,
)
from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import Project, ProjectService

_MAX_PROPOSAL_BYTES = 1_048_576
_MAX_JSON_DEPTH = 64


class ProposalService:
    """Own ``.arcavex/pending`` records without writing authored project source."""

    def __init__(
        self, projects: ProjectService, snapshots: ProjectSnapshotService
    ) -> None:
        self._projects = projects
        self._snapshots = snapshots

    def enqueue(
        self,
        *,
        project: Path,
        command_id: str,
        base_project_revision: str,
        actor: ProposalActor,
        command_payload: dict[str, object],
        created_at: datetime,
    ) -> ProjectProposal:
        """Atomically create a pending proposal after validating its filename identity."""
        loaded = self._projects.resolve(override=project)
        canonical_id = _command_id(command_id)
        try:
            proposal = ProjectProposal(
                command_id=canonical_id,
                project_path=str(loaded.root.resolve()),
                base_project_revision=base_project_revision,
                actor=actor,
                command_payload=command_payload,
                created_at=created_at,
            )
        except ValidationError as exc:
            raise _invalid_proposal(command_id, str(exc)) from exc
        try:
            payload = _serialize(proposal)
        except (PydanticSerializationError, TypeError, ValueError) as exc:
            raise _invalid_proposal(command_id, str(exc)) from exc
        with project_mutation_lock(loaded.root):
            loaded = self._projects.load(loaded.root)
            queue = _prepare_queue(loaded)
            path = queue / f"{canonical_id}.json"
            ensure_project_path_safe(loaded.root, path)
            try:
                _create(path, payload, loaded)
            except FileExistsError as exc:
                raise _invalid_command(
                    command_id, "a proposal with this command ID already exists"
                ) from exc
        return proposal

    def list_proposals(
        self, *, start: Path | None = None, project: Path | None = None
    ) -> ProposalListReport:
        """Return valid records in command-ID order and diagnose malformed entries."""
        loaded = self._projects.resolve(start, project)
        proposals: list[ProjectProposal] = []
        diagnostics: list[Diagnostic] = []
        queue = _queue_dir(loaded)
        try:
            ensure_project_path_safe(loaded.root, queue)
        except DiagnosticError as exc:
            diagnostics.extend(exc.diagnostics)
        else:
            queue_exists = queue.is_dir()
        if not diagnostics and queue_exists:
            for path in sorted(queue.glob("*.json"), key=lambda item: item.name):
                proposal, entry_diagnostics = _read(path, loaded)
                diagnostics.extend(entry_diagnostics)
                if proposal is not None:
                    proposals.append(proposal)
        return ProposalListReport(
            ok=not diagnostics,
            canonical_path=str(loaded.root.resolve()),
            proposals=proposals,
            diagnostics=diagnostics,
        )

    def approve(
        self,
        *,
        command_id: str,
        start: Path | None = None,
        project: Path | None = None,
    ) -> ProposalActionReport:
        """Authorize a current proposal without executing or mutating authored source."""
        loaded = self._projects.resolve(start, project)
        with project_mutation_lock(loaded.root):
            loaded = self._projects.load(loaded.root)
            proposal, failure = self._target(loaded, command_id)
            if failure is not None:
                return failure
            assert proposal is not None
            snapshot = self._snapshots.snapshot(project=loaded.root)
            if snapshot.project_revision != proposal.base_project_revision:
                return ProposalActionReport(
                    ok=False,
                    canonical_path=str(loaded.root.resolve()),
                    project_revision=snapshot.project_revision,
                    proposal=proposal,
                    diagnostics=[
                        diagnostic(
                            "ARC-PRJ-011",
                            "Proposal base project revision is stale",
                            file=str(self._path(loaded, str(proposal.command_id))),
                            hint=(
                                "Reload the project, inspect the changed revision manifest, and "
                                "submit a new proposal against the current project revision."
                            ),
                        )
                    ],
                )
            if proposal.state == "rejected":
                return self._state_failure(loaded, proposal, snapshot.project_revision)
            if proposal.state == "pending":
                proposal = proposal.model_copy(update={"state": "authorized"})
                _write(self._path(loaded, str(proposal.command_id)), proposal, loaded)
            return ProposalActionReport(
                ok=True,
                canonical_path=str(loaded.root.resolve()),
                project_revision=snapshot.project_revision,
                proposal=proposal,
            )

    def reject(
        self,
        *,
        command_id: str,
        reason: str,
        start: Path | None = None,
        project: Path | None = None,
    ) -> ProposalActionReport:
        """Persist an explicit, inspectable rejection without deleting the queue record."""
        loaded = self._projects.resolve(start, project)
        with project_mutation_lock(loaded.root):
            loaded = self._projects.load(loaded.root)
            proposal, failure = self._target(loaded, command_id)
            if failure is not None:
                return failure
            assert proposal is not None
            snapshot = self._snapshots.snapshot(project=loaded.root)
            if proposal.state == "authorized":
                return self._state_failure(loaded, proposal, snapshot.project_revision)
            if proposal.state == "pending":
                proposal = proposal.model_copy(
                    update={"state": "rejected", "rejection_reason": reason}
                )
                _write(self._path(loaded, str(proposal.command_id)), proposal, loaded)
            return ProposalActionReport(
                ok=True,
                canonical_path=str(loaded.root.resolve()),
                project_revision=snapshot.project_revision,
                proposal=proposal,
            )

    def _target(
        self, loaded: Project, command_id: str
    ) -> tuple[ProjectProposal | None, ProposalActionReport | None]:
        canonical_id = _command_id(command_id)
        path = self._path(loaded, canonical_id)
        try:
            ensure_project_path_safe(loaded.root, path)
        except DiagnosticError as exc:
            return None, ProposalActionReport(
                ok=False,
                canonical_path=str(loaded.root.resolve()),
                diagnostics=list(exc.diagnostics),
            )
        if not path.is_file():
            return None, ProposalActionReport(
                ok=False,
                canonical_path=str(loaded.root.resolve()),
                diagnostics=[
                    diagnostic(
                        "ARC-PRJ-012",
                        f"Proposal {canonical_id} does not exist",
                        file=str(path),
                        hint="List proposals and choose an existing command ID.",
                    )
                ],
            )
        proposal, diagnostics = _read(path, loaded)
        if proposal is None:
            return None, ProposalActionReport(
                ok=False,
                canonical_path=str(loaded.root.resolve()),
                diagnostics=diagnostics,
            )
        return proposal, None

    def _state_failure(
        self, loaded: Project, proposal: ProjectProposal, revision: str | None
    ) -> ProposalActionReport:
        return ProposalActionReport(
            ok=False,
            canonical_path=str(loaded.root.resolve()),
            project_revision=revision,
            proposal=proposal,
            diagnostics=[
                diagnostic(
                    "ARC-PRJ-012",
                    f"Proposal {proposal.command_id} is already {proposal.state}",
                    file=str(self._path(loaded, str(proposal.command_id))),
                    hint="Use a pending proposal, or submit a new command with a new UUID.",
                )
            ],
        )

    @staticmethod
    def _path(project: Project, command_id: str) -> Path:
        return _queue_dir(project) / f"{command_id}.json"


def _queue_dir(project: Project) -> Path:
    return project.root / ".arcavex" / "pending"


def _prepare_queue(project: Project) -> Path:
    working = project.root / ".arcavex"
    ensure_project_path_safe(project.root, working)
    working.mkdir(exist_ok=True)
    ensure_project_path_safe(project.root, working)
    queue = working / "pending"
    ensure_project_path_safe(project.root, queue)
    queue.mkdir(exist_ok=True)
    ensure_project_path_safe(project.root, queue)
    return queue


def _command_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise _invalid_command(value, "command ID must be a canonical UUIDv4") from exc
    canonical = str(parsed)
    if parsed.version != 4 or value != canonical:
        raise _invalid_command(value, "command ID must be a canonical UUIDv4")
    return canonical


def _invalid_command(value: str, detail: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-PRJ-009",
            f"Invalid proposal command ID {value!r}: {detail}",
            hint="Generate a canonical lowercase UUIDv4 and use it as the command ID.",
        )
    )


def _invalid_proposal(command_id: str, detail: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-PRJ-013",
            f"Invalid proposal {command_id}: {detail}",
            hint=(
                "Provide a canonical project path, SHA-256 base project revision, actor identity, "
                "timezone-aware timestamp, and JSON-serializable command payload."
            ),
        )
    )


def _read(path: Path, project: Project) -> tuple[ProjectProposal | None, list[Diagnostic]]:
    try:
        ensure_project_path_safe(project.root, path)
        if path.stat().st_size > _MAX_PROPOSAL_BYTES:
            raise ValueError(
                f"proposal exceeds size limit of {_MAX_PROPOSAL_BYTES} bytes"
            )
        ensure_project_path_safe(project.root, path)
        content = path.read_bytes()
        if len(content) > _MAX_PROPOSAL_BYTES:
            raise ValueError(
                f"proposal exceeds size limit of {_MAX_PROPOSAL_BYTES} bytes"
            )
        raw = json.loads(content.decode("utf-8"))
        if _exceeds_json_depth(raw, _MAX_JSON_DEPTH):
            raise ValueError(
                f"proposal JSON exceeds nesting limit of {_MAX_JSON_DEPTH} levels"
            )
        proposal = ProjectProposal.model_validate(raw)
        if path.stem != str(proposal.command_id):
            raise ValueError("filename does not match command_id")
        if proposal.project_path != str(project.root.resolve()):
            raise ValueError("project_path does not match this project")
        return proposal, []
    except DiagnosticError as exc:
        return None, list(exc.diagnostics)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        RecursionError,
        MemoryError,
        OverflowError,
    ) as exc:
        return None, [
            diagnostic(
                "ARC-PRJ-010",
                f"Malformed proposal queue entry: {exc}",
                file=str(path),
                hint=(
                    "Repair or remove this queue JSON record; other valid proposals remain "
                    "available."
                ),
            )
        ]


def _exceeds_json_depth(value: object, limit: int) -> bool:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limit:
            return True
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return False


def _write(path: Path, proposal: ProjectProposal, project: Project) -> None:
    payload = _serialize(proposal)
    ensure_project_path_safe(project.root, path)
    atomic_write_text(path, payload + "\n")


def _create(path: Path, payload: str, project: Project) -> None:
    ensure_project_path_safe(project.root, path)
    atomic_create_text(path, payload + "\n")


def _serialize(proposal: ProjectProposal) -> str:
    return json.dumps(
        proposal.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )

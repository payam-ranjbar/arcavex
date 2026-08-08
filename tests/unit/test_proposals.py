"""Versioned, revision-checked project proposal queue contracts."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arcavex.kernel.api import (
    ProjectProposal,
    ProposalActionReport,
    ProposalActor,
    ProposalListReport,
)
from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.fsutil import file_lock
from arcavex.services.project_policy import ProjectPolicyService
from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import ProjectService
from arcavex.services.proposals import ProposalService

_EARLY_ID = "00000000-0000-4000-8000-000000000001"
_LATE_ID = "00000000-0000-4000-8000-000000000002"
_LINKED_ID = "00000000-0000-4000-8000-000000000003"
_CREATED = datetime(2026, 8, 8, 12, 30, tzinfo=UTC)


def _project(root: Path) -> Path:
    project = root / "campaign"
    (project / "template").mkdir(parents=True)
    (project / "template/template.yaml").write_text(
        "version: 0.1.0\n", encoding="utf-8"
    )
    (project / "project.yaml").write_text(
        "name: launch\ntemplate: ./template\nformats: [square]\nlocales: []\n",
        encoding="utf-8",
    )
    return project


def _services() -> tuple[ProposalService, ProjectSnapshotService]:
    projects = ProjectService()
    snapshots = ProjectSnapshotService(projects)
    return ProposalService(projects, snapshots), snapshots


def _source_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".arcavex" not in path.relative_to(root).parts
    }


@contextmanager
def _linked_directory(link: Path, target: Path) -> Iterator[None]:
    """Create a real directory symlink or Windows junction for a safety test."""
    target.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"platform cannot create directory links: {exc}")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"platform cannot create directory junctions: {result.stderr}")
    try:
        yield
    finally:
        if link.is_symlink():
            link.unlink()
        elif getattr(link, "is_junction", lambda: False)():
            link.rmdir()


@contextmanager
def _linked_file(link: Path, target: Path) -> Iterator[None]:
    """Create a real file symlink when the platform permits it."""
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"platform cannot create file symlinks: {exc}")
    try:
        yield
    finally:
        if link.is_symlink():
            link.unlink()


def _enqueue(
    proposals: ProposalService,
    snapshots: ProjectSnapshotService,
    root: Path,
    command_id: str = _EARLY_ID,
) -> ProjectProposal:
    revision = snapshots.snapshot(project=root).project_revision
    assert revision is not None
    return proposals.enqueue(
        project=root,
        command_id=command_id,
        base_project_revision=revision,
        actor=ProposalActor(id="agent-7", display_name="Studio Agent"),
        command_payload={"kind": "set_display_name", "layer_id": "title", "value": "Hero"},
        created_at=_CREATED,
    )


def test_enqueue_writes_versioned_canonical_proposal_without_touching_source_or_revisions(
    tmp_path: Path,
) -> None:
    """Queueing review work must never masquerade as a semantic project mutation."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    ProjectPolicyService(ProjectService(), snapshots).set_policy(
        project=root, mode="review", extensions="unrestricted"
    )
    before_snapshot = snapshots.snapshot(project=root)
    before_source = _source_bytes(root)

    proposal = _enqueue(proposals, snapshots, root)
    after_snapshot = snapshots.snapshot(project=root)

    assert proposal == ProjectProposal(
        command_id=_EARLY_ID,
        project_path=str(root.resolve()),
        base_project_revision=before_snapshot.project_revision,
        actor=ProposalActor(id="agent-7", display_name="Studio Agent"),
        command_payload={
            "kind": "set_display_name",
            "layer_id": "title",
            "value": "Hero",
        },
        created_at=_CREATED,
        state="pending",
    )
    assert _source_bytes(root) == before_source
    assert after_snapshot.project_revision == before_snapshot.project_revision
    assert after_snapshot.render_revision == before_snapshot.render_revision
    queue_file = root / ".arcavex/pending" / f"{_EARLY_ID}.json"
    assert queue_file.is_file()
    assert json.loads(queue_file.read_text(encoding="utf-8")) == proposal.model_dump(
        mode="json"
    )
    assert not list(queue_file.parent.glob(".*.tmp"))


@pytest.mark.parametrize(
    "command_id", ["../escape", "not-a-uuid", "00000000-0000-0000-0000-000000000000"]
)
def test_enqueue_rejects_non_uuid_or_unsafe_command_ids(
    tmp_path: Path, command_id: str
) -> None:
    """Unsafe IDs must not choose queue filenames or traverse outside the project."""
    root = _project(tmp_path)
    proposals, snapshots = _services()

    with pytest.raises(DiagnosticError) as exc:
        _enqueue(proposals, snapshots, root, command_id)

    assert exc.value.diagnostics[0].code == "ARC-PRJ-009"
    assert not (root / ".arcavex").exists()
    assert not (root.parent / "escape.json").exists()


def test_enqueue_rejects_linked_arcavex_directory_before_external_io(
    tmp_path: Path,
) -> None:
    """Following a linked .arcavex directory would publish the queue outside the project."""
    root = _project(tmp_path)
    outside = tmp_path / "outside-working-state"
    proposals, snapshots = _services()

    with _linked_directory(root / ".arcavex", outside):
        with pytest.raises(DiagnosticError) as exc:
            _enqueue(proposals, snapshots, root)

        assert exc.value.diagnostics[0].code == "ARC-PRJ-014"
        assert list(outside.iterdir()) == []


def test_enqueue_rejects_linked_pending_directory_before_external_io(
    tmp_path: Path,
) -> None:
    """A safe lock directory must not make a linked pending child acceptable."""
    root = _project(tmp_path)
    (root / ".arcavex").mkdir()
    outside = tmp_path / "outside-pending"
    proposals, snapshots = _services()

    with _linked_directory(root / ".arcavex/pending", outside):
        with pytest.raises(DiagnosticError) as exc:
            _enqueue(proposals, snapshots, root)

        assert exc.value.diagnostics[0].code == "ARC-PRJ-014"
        assert list(outside.iterdir()) == []


def test_list_rejects_linked_record_and_continues_with_valid_entries(
    tmp_path: Path,
) -> None:
    """A linked record must not be read outside the project or hide a valid queue entry."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    valid = _enqueue(proposals, snapshots, root)
    outside = tmp_path / "outside-record.json"
    linked_payload = ProjectProposal.model_validate(
        {**valid.model_dump(mode="json"), "command_id": _LINKED_ID}
    )
    outside.write_text(linked_payload.model_dump_json(), encoding="utf-8")
    linked = root / ".arcavex/pending" / f"{_LINKED_ID}.json"

    with _linked_file(linked, outside):
        report = proposals.list_proposals(project=root)

        assert [str(item.command_id) for item in report.proposals] == [_EARLY_ID]
        assert [diag.code for diag in report.diagnostics] == ["ARC-PRJ-014"]
        assert outside.read_text(encoding="utf-8") == linked_payload.model_dump_json()


def test_enqueue_reports_invalid_proposal_content_separately_from_command_id(
    tmp_path: Path,
) -> None:
    """A bad revision is a malformed record, not an invalid UUID diagnostic."""
    root = _project(tmp_path)
    proposals, _snapshots = _services()

    with pytest.raises(DiagnosticError) as exc:
        proposals.enqueue(
            project=root,
            command_id=_EARLY_ID,
            base_project_revision="not-a-revision",
            actor=ProposalActor(id="agent-7"),
            command_payload={"kind": "set_display_name"},
            created_at=_CREATED,
        )

    assert exc.value.diagnostics[0].code == "ARC-PRJ-013"
    assert not (root / ".arcavex").exists()


def test_enqueue_rejects_a_payload_that_cannot_be_stored_as_json(tmp_path: Path) -> None:
    """Opaque means arbitrary JSON; non-JSON Python objects must fail before queue creation."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    revision = snapshots.snapshot(project=root).project_revision
    assert revision is not None

    with pytest.raises(DiagnosticError) as exc:
        proposals.enqueue(
            project=root,
            command_id=_EARLY_ID,
            base_project_revision=revision,
            actor=ProposalActor(id="agent-7"),
            command_payload={"value": object()},
            created_at=_CREATED,
        )

    assert exc.value.diagnostics[0].code == "ARC-PRJ-013"
    assert not (root / ".arcavex").exists()


def test_list_is_deterministic_and_reports_malformed_entries(tmp_path: Path) -> None:
    """One corrupt queue record must not hide valid proposals or destabilize ordering."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    _enqueue(proposals, snapshots, root, _LATE_ID)
    _enqueue(proposals, snapshots, root, _EARLY_ID)
    malformed = root / ".arcavex/pending/broken.json"
    malformed.write_text("{not-json", encoding="utf-8")

    report = proposals.list_proposals(project=root)

    assert isinstance(report, ProposalListReport)
    assert not report.ok
    assert [str(item.command_id) for item in report.proposals] == [_EARLY_ID, _LATE_ID]
    actual_diagnostics = [
        (diag.code, diag.source.file if diag.source else None)
        for diag in report.diagnostics
    ]
    assert actual_diagnostics == [("ARC-PRJ-010", str(malformed))]


def test_list_bounds_oversized_and_deep_json_while_continuing_valid_records(
    tmp_path: Path,
) -> None:
    """Unbounded decoding must not let one hostile record abort the complete proposal list."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    _enqueue(proposals, snapshots, root)
    queue = root / ".arcavex/pending"
    deep = queue / "deep.json"
    deep.write_text("[" * 2_000 + "0" + "]" * 2_000, encoding="utf-8")
    oversized = queue / "oversized.json"
    oversized.write_bytes(b" " * 1_048_577 + b"{}")

    report = proposals.list_proposals(project=root)

    assert [str(item.command_id) for item in report.proposals] == [_EARLY_ID]
    assert [diag.code for diag in report.diagnostics] == ["ARC-PRJ-010", "ARC-PRJ-010"]
    assert report.diagnostics[0].source is not None
    assert report.diagnostics[0].source.file == str(deep)
    assert "nesting limit" in report.diagnostics[0].message
    assert report.diagnostics[1].source is not None
    assert report.diagnostics[1].source.file == str(oversized)
    assert "size limit" in report.diagnostics[1].message


def test_approve_authorizes_but_does_not_apply_or_change_source(tmp_path: Path) -> None:
    """Foundation approval must return authorization honestly, without invented YAML mutation."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    _enqueue(proposals, snapshots, root)
    before_source = _source_bytes(root)

    report = proposals.approve(project=root, command_id=_EARLY_ID)

    assert isinstance(report, ProposalActionReport)
    assert report.ok
    assert report.proposal is not None
    assert report.proposal.state == "authorized"
    assert "applied" not in report.model_dump(mode="json")
    assert _source_bytes(root) == before_source
    assert (root / ".arcavex/pending" / f"{_EARLY_ID}.json").is_file()


def test_approve_waits_for_shared_lock_then_rereads_latest_queue_state(
    tmp_path: Path,
) -> None:
    """A read-before-lock approval would overwrite a concurrent rejection with authorization."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    pending = _enqueue(proposals, snapshots, root)
    queue_file = root / ".arcavex/pending" / f"{_EARLY_ID}.json"
    lock_path = root / ".arcavex/project.lock"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with file_lock(lock_path):
            future = pool.submit(
                proposals.approve, project=root, command_id=_EARLY_ID
            )
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.2)
            rejected = pending.model_copy(
                update={"state": "rejected", "rejection_reason": "external decision"}
            )
            queue_file.write_text(rejected.model_dump_json(), encoding="utf-8")

        report = future.result(timeout=2)

    assert not report.ok
    assert report.proposal is not None and report.proposal.state == "rejected"
    assert ProjectProposal.model_validate_json(queue_file.read_text(encoding="utf-8")) == rejected


def test_enqueue_waits_for_shared_lock_and_never_replaces_an_existing_id(
    tmp_path: Path,
) -> None:
    """Existence-before-lock plus replace would let a duplicate command overwrite queue state."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    revision = snapshots.snapshot(project=root).project_revision
    assert revision is not None
    queue = root / ".arcavex/pending"
    lock_path = root / ".arcavex/project.lock"
    existing = ProjectProposal(
        command_id=_EARLY_ID,
        project_path=str(root.resolve()),
        base_project_revision=revision,
        actor=ProposalActor(id="first-writer"),
        command_payload={"kind": "existing"},
        created_at=_CREATED,
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with file_lock(lock_path):
            future = pool.submit(
                proposals.enqueue,
                project=root,
                command_id=_EARLY_ID,
                base_project_revision=revision,
                actor=ProposalActor(id="second-writer"),
                command_payload={"kind": "replacement"},
                created_at=_CREATED,
            )
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.2)
            queue.mkdir(exist_ok=True)
            queue_file = queue / f"{_EARLY_ID}.json"
            queue_file.write_text(existing.model_dump_json(), encoding="utf-8")

        with pytest.raises(DiagnosticError):
            future.result(timeout=2)

    assert ProjectProposal.model_validate_json(queue_file.read_text(encoding="utf-8")) == existing


def test_stale_approval_leaves_source_and_pending_record_byte_identical(
    tmp_path: Path,
) -> None:
    """A stale base revision must cause no source write and no destructive queue transition."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    _enqueue(proposals, snapshots, root)
    queue_file = root / ".arcavex/pending" / f"{_EARLY_ID}.json"
    (root / "project.ui.yaml").write_text(
        "version: 1\nlayers:\n  title:\n    locked: true\n", encoding="utf-8"
    )
    before_source = _source_bytes(root)
    before_queue = queue_file.read_bytes()

    report = proposals.approve(project=root, command_id=_EARLY_ID)

    assert not report.ok
    assert report.proposal is not None and report.proposal.state == "pending"
    assert [diag.code for diag in report.diagnostics] == ["ARC-PRJ-011"]
    assert _source_bytes(root) == before_source
    assert queue_file.read_bytes() == before_queue


def test_rejection_is_explicit_recoverable_and_idempotent(tmp_path: Path) -> None:
    """Rejecting must preserve an inspectable record and retry deterministically."""
    root = _project(tmp_path)
    proposals, snapshots = _services()
    _enqueue(proposals, snapshots, root)

    first = proposals.reject(
        project=root, command_id=_EARLY_ID, reason="Not aligned with the campaign"
    )
    queue_file = root / ".arcavex/pending" / f"{_EARLY_ID}.json"
    first_bytes = queue_file.read_bytes()
    second = proposals.reject(
        project=root, command_id=_EARLY_ID, reason="Not aligned with the campaign"
    )

    assert first.ok and second.ok
    assert first.proposal is not None and first.proposal.state == "rejected"
    assert first.proposal.rejection_reason == "Not aligned with the campaign"
    assert second.proposal == first.proposal
    assert queue_file.read_bytes() == first_bytes


def test_missing_proposal_returns_structured_diagnostic(tmp_path: Path) -> None:
    """Approving an absent command must remain inside the report boundary."""
    root = _project(tmp_path)
    proposals, _snapshots = _services()

    report = proposals.approve(project=root, command_id=_EARLY_ID)

    assert not report.ok
    assert report.proposal is None
    assert [diag.code for diag in report.diagnostics] == ["ARC-PRJ-012"]

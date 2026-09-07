"""Atomicity of the transaction writer: all of it lands, or none of it does.

A semantic transaction can touch several files — the template, a data file, an override patch.
The failure that matters is the partial one: template.yaml rewritten, the override not yet, and a
crash between them leaves a project no revision has ever described. The staged-write protocol
exists so that state cannot occur, and these tests attack each stage of it.

The writer here knows nothing about commands. It is handed the complete new content for each file
and a validator over the staged state; deciding *what* to write is Task 5's service.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.editor.transaction import StagedWrite, apply_staged_writes


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "template.yaml").write_text("root: {}\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "event.yaml").write_text("title: Old\n", encoding="utf-8")
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".arcavex" not in path.parts
    }


def test_all_writes_land_together(project: Path) -> None:
    changed = apply_staged_writes(
        project,
        [
            StagedWrite(relative="template.yaml", content=b"root: {new: true}\n"),
            StagedWrite(relative="data/event.yaml", content=b"title: New\n"),
            StagedWrite(relative="overrides/square.patch.yaml", content=b"ops: []\n"),
        ],
    )

    assert (project / "template.yaml").read_bytes() == b"root: {new: true}\n"
    assert (project / "data" / "event.yaml").read_bytes() == b"title: New\n"
    assert (project / "overrides" / "square.patch.yaml").read_bytes() == b"ops: []\n"
    assert {(entry.path, entry.change) for entry in changed} == {
        ("template.yaml", "modified"),
        ("data/event.yaml", "modified"),
        ("overrides/square.patch.yaml", "created"),
    }


def test_a_delete_is_a_staged_write_too(project: Path) -> None:
    changed = apply_staged_writes(
        project, [StagedWrite(relative="data/event.yaml", content=None)]
    )

    assert not (project / "data" / "event.yaml").exists()
    assert [(entry.path, entry.change) for entry in changed] == [("data/event.yaml", "deleted")]


def test_a_failed_validation_writes_nothing(project: Path) -> None:
    """The validator sees the staged state; if it refuses, the project is byte-identical."""
    before = _snapshot(project)

    def refuse(staged_root: Path) -> None:
        # Prove the validator is looking at the staged content, not the live project.
        assert (staged_root / "template.yaml").read_bytes() == b"root: {broken\n"
        raise DiagnosticError(
            diagnostic("ARC-TPL-001", "Staged template does not parse", file="template.yaml")
        )

    with pytest.raises(DiagnosticError):
        apply_staged_writes(
            project,
            [
                StagedWrite(relative="template.yaml", content=b"root: {broken\n"),
                StagedWrite(relative="data/event.yaml", content=b"title: New\n"),
            ],
            validate=refuse,
        )

    assert _snapshot(project) == before


def test_a_failure_replacing_a_later_file_rolls_back_the_earlier_ones(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window between the first replace and the last is where rollback must save us."""
    import arcavex.services.editor.transaction as transaction_module

    before = _snapshot(project)
    real_replace = transaction_module._replace_file

    calls = {"count": 0}

    def failing_replace(source: Path, destination: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("disk full")
        real_replace(source, destination)

    monkeypatch.setattr(transaction_module, "_replace_file", failing_replace)

    with pytest.raises(DiagnosticError) as raised:
        apply_staged_writes(
            project,
            [
                StagedWrite(relative="template.yaml", content=b"root: {new: true}\n"),
                StagedWrite(relative="data/event.yaml", content=b"title: New\n"),
            ],
        )

    assert raised.value.diagnostics[0].code == "ARC-EDT-002"
    assert _snapshot(project) == before, "the first replace must have been rolled back"


def test_paths_may_not_escape_the_project(project: Path) -> None:
    for hostile in ("../outside.yaml", "data/../../outside.yaml"):
        with pytest.raises(DiagnosticError) as raised:
            apply_staged_writes(project, [StagedWrite(relative=hostile, content=b"x")])
        assert raised.value.diagnostics[0].code == "ARC-PRJ-014"
    assert not (project.parent / "outside.yaml").exists()


def test_engine_managed_state_is_not_writable_through_a_transaction(project: Path) -> None:
    """History and the queue live under .arcavex; a command that could write there could forge
    its own history."""
    with pytest.raises(DiagnosticError) as raised:
        apply_staged_writes(
            project, [StagedWrite(relative=".arcavex/history/forged.json", content=b"{}")]
        )

    assert raised.value.diagnostics[0].code == "ARC-PRJ-014"


def test_no_stray_staging_artifacts_survive_success_or_failure(project: Path) -> None:
    apply_staged_writes(project, [StagedWrite(relative="template.yaml", content=b"ok: 1\n")])

    def refuse(_: Path) -> None:
        raise DiagnosticError(diagnostic("ARC-TPL-001", "no", file="template.yaml"))

    with pytest.raises(DiagnosticError):
        apply_staged_writes(
            project, [StagedWrite(relative="template.yaml", content=b"bad\n")], validate=refuse
        )

    staging = [
        path
        for path in project.rglob("*")
        if ".arcavex" in path.parts and "staging" in path.as_posix()
    ]
    assert staging == [], f"staging leftovers: {staging}"

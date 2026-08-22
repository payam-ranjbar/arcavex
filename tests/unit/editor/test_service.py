"""The editor service: one transaction in, one honest report out.

This is where every Phase 2 guarantee composes: the lock, the revision guard, the policy gate,
the tree primitives, the staged atomic writer, and the history store. Each test drives the public
`apply`/`undo`/`redo`/`history` surface the Facade, MCP, and CLI all delegate to, against a real
project on disk.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from arcavex.services.editor.service import EditorService
from arcavex.services.library import Library
from arcavex.services.project_policy import ProjectPolicyService
from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import ProjectService
from arcavex.services.proposals import ProposalService
from arcavex.services.template.loader import load_yaml

_TEMPLATE = """\
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
preview_data: {}
root:
  type: group
  id: root
  children:
    - id: background   # a comment that must survive editing
      type: shape
      shape: rect
      style: {fill: "#111111"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
    - id: title
      type: text
      text: "Old headline"
      style: {font: Inter, font_size: 24pt, color: "#FFFFFF"}
      constraints:
        anchor: {top: parent.top+20px, left: parent.left+20px}
        size: {w: 80%, h: fit_content}
    - id: badge
      type: shape
      shape: rect
      style: {fill: "#AA3355"}
      constraints:
        anchor: {top: parent.top+150px, left: parent.left+20px}
        size: {w: 30px, h: 30px}
"""

_PROJECT_MANIFEST = """\
name: editable
template: template.yaml
locales: []
formats:
  - square
data: data/data.yaml
"""


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "editable"
    (root / "data").mkdir(parents=True)
    (root / "template.yaml").write_text(_TEMPLATE, encoding="utf-8")
    (root / "project.yaml").write_text(_PROJECT_MANIFEST, encoding="utf-8")
    (root / "data" / "data.yaml").write_text("{}\n", encoding="utf-8")
    return root


@pytest.fixture()
def service(tmp_path: Path) -> EditorService:
    from arcavex.bootstrap import build_editor_service

    return build_editor_service(library=Library(tmp_path / "library"))


def _projects(tmp_path: Path) -> ProjectService:
    return ProjectService(Library(tmp_path / "library"))


def _transaction(
    project: Path,
    base: str,
    commands: list[dict[str, Any]],
    *,
    actor: str = "test",
) -> dict[str, Any]:
    return {
        "command_id": str(uuid.uuid4()),
        "project_path": str(project.resolve()),
        "base_project_revision": base,
        "actor": {"id": actor},
        "target": {"format": "square"},
        "commands": commands,
    }


def _revision(tmp_path: Path, project: Path) -> str:
    snapshots = ProjectSnapshotService(_projects(tmp_path))
    report = snapshots.snapshot(project=project)
    assert report.project_revision is not None
    return report.project_revision


# ------------------------------------------------------------------------------------ execution


def test_set_text_edits_the_file_and_returns_an_inverse(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    base = _revision(tmp_path, project)

    report = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "New"}])
    )

    assert report.ok, report.diagnostics
    template = (project / "template.yaml").read_text(encoding="utf-8")
    assert 'text: "New"' in template or "text: New" in template
    assert "# a comment that must survive editing" in template, "round-trip must keep comments"
    assert report.project_revision != base
    assert [c.path for c in report.changed] == ["template.yaml"]
    assert report.changed_layer_ids == ["title"]
    assert report.inverse is not None
    # Inverses are raw restorations, not semantic opposites: undo must put back the exact
    # authored value so the file returns to the exact revision history recorded.
    inverse_command = report.inverse.commands[0]
    assert inverse_command.kind == "set_property"
    assert inverse_command.keypath == "text"  # type: ignore[union-attr]
    assert inverse_command.value == "Old headline"  # type: ignore[union-attr]
    assert report.inverse.base_project_revision == report.project_revision


def test_a_stale_base_revision_is_a_conflict_with_named_files(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """Naming the moved files needs the base's manifest, which the editor remembers whenever it
    sees a revision — so the flow here is the real one: edit, external change, edit again."""
    first = service.apply(
        _transaction(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_text", "layer_id": "title", "text": "First"}],
        )
    )
    assert first.ok and first.project_revision is not None
    base = first.project_revision

    # An external writer edits the project after our snapshot.
    (project / "data" / "data.yaml").write_text("changed: true\n", encoding="utf-8")

    report = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "New"}])
    )

    assert not report.ok
    assert report.conflict is not None
    assert report.conflict.expected_project_revision == base
    assert any(c.path == "data/data.yaml" for c in report.conflict.changed)
    assert "First" in (project / "template.yaml").read_text(encoding="utf-8")


def test_a_conflict_against_an_unseen_base_still_refuses_without_naming_files(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """A base the editor never saw cannot be diffed — the refusal stands, the list is empty."""
    base = _revision(tmp_path, project)
    (project / "data" / "data.yaml").write_text("changed: true\n", encoding="utf-8")

    report = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "New"}])
    )

    assert not report.ok
    assert report.conflict is not None
    assert report.conflict.changed == []
    assert "Old headline" in (project / "template.yaml").read_text(encoding="utf-8")


def test_a_validation_failure_writes_nothing(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """Setting a property to something the compiler rejects must leave the file untouched."""
    base = _revision(tmp_path, project)
    before = (project / "template.yaml").read_bytes()

    report = service.apply(
        _transaction(
            project,
            base,
            [
                {
                    "kind": "set_property",
                    "layer_id": "title",
                    "keypath": "style.font_size",
                    "value": "not-a-size",
                }
            ],
        )
    )

    assert not report.ok
    assert report.diagnostics, "the compiler's refusal must surface"
    assert (project / "template.yaml").read_bytes() == before


def test_transform_and_structural_commands_apply_together_atomically(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    base = _revision(tmp_path, project)

    report = service.apply(
        _transaction(
            project,
            base,
            [
                {"kind": "translate", "layer_ids": ["badge"], "dx_pt": 12.0, "dy_pt": -6.0},
                {"kind": "rotate", "layer_id": "badge", "degrees": 30.0},
                {"kind": "reorder", "layer_id": "badge", "parent_id": "root", "index": 0},
            ],
        )
    )

    assert report.ok, report.diagnostics
    raw = load_yaml(project / "template.yaml")
    first = raw["root"]["children"][0]
    assert first["id"] == "badge"
    assert first["transform"]["translate"] == [12.0, -6.0]
    assert first["transform"]["rotate"] == 30.0
    # One transaction, one inverse: undoing restores order, rotation, and position together.
    # Field edits invert as raw restorations of the touched field; the reorder inverts exactly.
    assert report.inverse is not None
    assert {c.kind for c in report.inverse.commands} == {"set_property", "reorder"}


def test_delete_returns_a_restoring_inverse(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    base = _revision(tmp_path, project)

    report = service.apply(
        _transaction(project, base, [{"kind": "delete", "layer_ids": ["badge"]}])
    )

    assert report.ok, report.diagnostics
    assert report.inverse is not None
    restore = report.inverse.commands[0]
    assert restore.kind == "splice_children"
    assert restore.entries[0]["id"] == "badge"  # type: ignore[union-attr]

    # Applying the inverse brings the node back at its original position.
    undo_report = service.apply(report.inverse.model_dump(mode="json"))
    assert undo_report.ok, undo_report.diagnostics
    raw = load_yaml(project / "template.yaml")
    assert [child["id"] for child in raw["root"]["children"]] == [
        "background",
        "title",
        "badge",
    ]


def test_a_locked_layer_is_refused_at_the_engine_boundary(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    projects = _projects(tmp_path)
    from arcavex.kernel.api import LayerUIMetadata, ProjectUIMetadata

    projects.save_ui_metadata(
        projects.load(project),
        ProjectUIMetadata(layers={"badge": LayerUIMetadata(locked=True)}),
    )
    base = _revision(tmp_path, project)
    before = (project / "template.yaml").read_bytes()

    report = service.apply(
        _transaction(project, base, [{"kind": "delete", "layer_ids": ["badge"]}])
    )

    assert not report.ok
    assert any(d.code == "ARC-EDT-006" for d in report.diagnostics)
    assert (project / "template.yaml").read_bytes() == before


# --------------------------------------------------------------------------------------- policy


def test_read_only_mode_refuses_every_mutation(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    projects = _projects(tmp_path)
    policies = ProjectPolicyService(projects, ProjectSnapshotService(projects))
    policies.set_policy(project=project, mode="read_only", extensions="unrestricted")
    base = _revision(tmp_path, project)

    report = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "New"}])
    )

    assert not report.ok
    assert any(d.code == "ARC-EDT-009" for d in report.diagnostics)
    assert "Old headline" in (project / "template.yaml").read_text(encoding="utf-8")


def test_review_mode_queues_instead_of_executing(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    projects = _projects(tmp_path)
    policies = ProjectPolicyService(projects, ProjectSnapshotService(projects))
    policies.set_policy(project=project, mode="review", extensions="unrestricted")
    base = _revision(tmp_path, project)

    report = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "New"}])
    )

    assert report.ok
    assert report.queued_command_id is not None
    assert "Old headline" in (project / "template.yaml").read_text(encoding="utf-8")

    proposals = ProposalService(projects, ProjectSnapshotService(projects))
    queued = proposals.list_proposals(project=project)
    assert [str(p.command_id) for p in queued.proposals] == [str(report.queued_command_id)]


def test_an_authorized_proposal_executes_under_a_fresh_revision_check(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    projects = _projects(tmp_path)
    policies = ProjectPolicyService(projects, ProjectSnapshotService(projects))
    policies.set_policy(project=project, mode="review", extensions="unrestricted")
    base = _revision(tmp_path, project)
    queued = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "New"}])
    )
    assert queued.queued_command_id is not None

    proposals = ProposalService(projects, ProjectSnapshotService(projects))
    proposals.approve(project=project, command_id=str(queued.queued_command_id))

    report = service.apply_authorized(project, str(queued.queued_command_id))

    assert report.ok, report.diagnostics
    assert "New" in (project / "template.yaml").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------------- undo / redo


def test_undo_and_redo_round_trip_through_history(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    base = _revision(tmp_path, project)
    applied = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "New"}])
    )
    assert applied.ok

    history = service.history(project)
    assert history.can_undo and not history.can_redo

    undone = service.undo(project)
    assert undone.ok, undone.diagnostics
    assert "Old headline" in (project / "template.yaml").read_text(encoding="utf-8")
    assert service.history(project).can_redo

    redone = service.redo(project)
    assert redone.ok, redone.diagnostics
    assert "New" in (project / "template.yaml").read_text(encoding="utf-8")


def test_an_external_edit_closes_the_redo_line(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    base = _revision(tmp_path, project)
    applied = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "New"}])
    )
    assert applied.ok
    undone = service.undo(project)
    assert undone.ok

    # Someone else edits the project while our redo is pending.
    (project / "data" / "data.yaml").write_text("external: true\n", encoding="utf-8")

    history = service.history(project)
    assert not history.can_redo
    assert history.branched_by_external_edit
    refused = service.redo(project)
    assert not refused.ok


def test_undo_with_nothing_to_undo_is_a_report_not_a_crash(
    service: EditorService, project: Path
) -> None:
    report = service.undo(project)

    assert not report.ok
    assert report.diagnostics


# ------------------------------------------------------------------------------- display names


def test_set_display_name_edits_ui_metadata_not_the_template(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    base = _revision(tmp_path, project)
    template_before = (project / "template.yaml").read_bytes()

    report = service.apply(
        _transaction(
            project,
            base,
            [{"kind": "set_display_name", "layer_id": "title", "display_name": "Headline"}],
        )
    )

    assert report.ok, report.diagnostics
    assert (project / "template.yaml").read_bytes() == template_before
    projects = _projects(tmp_path)
    metadata = projects.load_ui_metadata(projects.load(project))
    assert metadata.layers["title"].display_name == "Headline"


# ------------------------------------------------------------------ malformed transactions


def test_a_malformed_transaction_names_every_field_it_is_missing(
    service: EditorService,
) -> None:
    """A refusal has to teach the caller the shape, or a client cannot converge on it.

    An AI client reaches this tool with no schema in front of it: the MCP catalog carries the
    tool's name, not the transaction's field names. Answering "5 validation error(s)" with a
    hint of "command_id" gives it a number and a bare token, and adding a correct field makes
    the count go *up* — a gradient pointing away from success. Every missing field has to be
    named, with what is wrong with it, in one answer.
    """
    report = service.apply({})

    assert report.ok is False
    detail = " ".join(
        f"{d.message} {d.hint or ''}" for d in report.diagnostics if d.code == "ARC-EDT-010"
    )
    for field in ("command_id", "project_path", "base_project_revision", "commands"):
        assert field in detail, f"the refusal never mentions {field!r}: {detail}"
    assert "required" in detail.lower()


def test_a_partly_formed_transaction_names_only_what_is_still_wrong(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """Progress must be visible: fixing a field removes it from the answer."""
    first = service.apply({"command_id": str(uuid.uuid4())})
    second = service.apply(
        {
            "command_id": str(uuid.uuid4()),
            "project_path": str(project.resolve()),
            "base_project_revision": _revision(tmp_path, project),
        }
    )

    # The message alone: the hint is a constant description of the shape, so it names every
    # field by design and cannot show progress.
    first_detail = " ".join(d.message for d in first.diagnostics)
    second_detail = " ".join(d.message for d in second.diagnostics)

    assert "command_id" not in second_detail
    assert "project_path" not in second_detail
    assert "commands" in second_detail
    # The answer gets shorter as the caller gets closer, rather than longer.
    assert len(second_detail) < len(first_detail)

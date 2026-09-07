"""The editor service: one transaction in, one honest report out.

This is where every Phase 2 guarantee composes: the lock, the revision guard, the policy gate,
the tree primitives, the staged atomic writer, and the history store. Each test drives the public
`apply`/`undo`/`redo`/`history` surface the Facade, MCP, and CLI all delegate to, against a real
project on disk.
"""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from typing import Any

import pytest

from arcavex.kernel.editor import COMMAND_FIELDS, SemanticTransaction
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
  story: {canvas: {width: 200px, height: 400px, dpi: 72}}
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
  - story
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


def test_an_empty_transaction_states_the_whole_shape_in_one_answer(
    service: EditorService,
) -> None:
    """The skill promises that an empty transaction makes the engine state the exact shape.

    It did state the envelope, but each command's fields only surfaced once the envelope was
    already right -- so a caller learned `set_text` needs `layer_id` and `text` one round trip
    later than promised. The hint has to carry every command kind with its fields, and the
    optional `scope`/`target` semantics, so one refusal is enough to compose a valid
    transaction.
    """
    report = service.apply({})

    assert report.ok is False
    message = " ".join(d.message for d in report.diagnostics if d.code == "ARC-EDT-010")
    for field in ("command_id", "project_path", "base_project_revision", "actor", "commands"):
        assert field in message, f"the message never names {field!r}: {message}"
    hint = " ".join(d.hint or "" for d in report.diagnostics if d.code == "ARC-EDT-010")
    assert "scope" in hint and "shared" in hint and "format" in hint
    for kind, fields in COMMAND_FIELDS.items():
        assert kind in hint, f"the hint never names command {kind!r}: {hint}"
        for field in fields:
            assert field.rstrip("?") in hint, f"{kind}.{field} missing from the hint: {hint}"
    # The real field names, not the ones an older description guessed at.
    assert "degrees" in hint and "remove_count" in hint


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


# ------------------------------------------------------- templates outside the project


def _project_pinning_an_outside_template(tmp_path: Path) -> Path:
    """The shape `project new --template <path>` produces: the template lives elsewhere."""
    outside = tmp_path / "authored"
    outside.mkdir()
    (outside / "template.yaml").write_text(_TEMPLATE, encoding="utf-8")

    project = tmp_path / "pinned"
    (project / "data").mkdir(parents=True)
    (project / "project.yaml").write_text(
        "name: pinned\ntemplate: ../authored\nlocales: []\n"
        "formats:\n  - square\ndata: data/data.yaml\n",
        encoding="utf-8",
    )
    (project / "data" / "data.yaml").write_text("{}\n", encoding="utf-8")
    return project


def test_a_template_outside_the_project_is_refused_with_the_way_out(
    service: EditorService, tmp_path: Path
) -> None:
    """Editing must not fail with a path the user never typed.

    `project new --template <path>` pins the template where it lives, outside the project. The
    editor stages an overlay inside the project and validates it there, so the relative pin
    resolved into the staging directory and the edit died with "File not found: ...\authored" --
    a path naming neither the project nor anything the person wrote. Worse, the write itself
    would have landed on a template.yaml *inside* the project, silently making a second template
    the project does not use.

    An external template is refused for the same reason a library one is: it is shared, and this
    editor only writes inside the project it was given. The refusal has to say so and name the
    command that fixes it.
    """
    project = _project_pinning_an_outside_template(tmp_path)

    report = service.apply(
        _transaction(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_text", "layer_id": "title", "text": "x"}],
        )
    )

    assert report.ok is False
    codes = [d.code for d in report.diagnostics]
    assert "ARC-EDT-008" in codes, codes
    detail = " ".join(f"{d.message} {d.hint or ''}" for d in report.diagnostics)
    assert "detach" in detail.lower(), detail
    assert "File not found" not in detail


def test_display_names_still_work_on_a_project_with_an_outside_template(
    service: EditorService, tmp_path: Path
) -> None:
    """Renaming writes project.ui.yaml, which is the project's own file, so it stays allowed."""
    project = _project_pinning_an_outside_template(tmp_path)

    report = service.apply(
        _transaction(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_display_name", "layer_id": "title", "display_name": "Headline"}],
        )
    )

    assert report.ok, [d.model_dump() for d in report.diagnostics]


# ------------------------------------------------------------- refusals a client can read


def test_a_conflict_also_carries_a_coded_diagnostic(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """A conflict must be legible to a client that reads diagnostics, not only to one that
    knows to look at the `conflict` field.

    Every other refusal on this surface arrives as a coded, located diagnostic, and clients are
    built to render that list. A conflict arrived with `diagnostics: []`, so a client following
    the convention reported nothing at all -- the edit simply appeared to do nothing.
    """
    base = _revision(tmp_path, project)
    first = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "First"}])
    )
    assert first.ok

    stale = service.apply(
        _transaction(project, base, [{"kind": "set_text", "layer_id": "title", "text": "Second"}])
    )

    assert stale.ok is False
    assert stale.conflict is not None
    codes = [d.code for d in stale.diagnostics]
    assert "ARC-EDT-012" in codes, codes
    detail = " ".join(d.message for d in stale.diagnostics)
    assert "template.yaml" in detail, detail


def _project_with_a_nested_template(tmp_path: Path) -> Path:
    """The shape `template detach` produces: the template inside the project, in a subdirectory."""
    project = tmp_path / "detached"
    nested = project / "templates" / "kit"
    nested.mkdir(parents=True)
    (nested / "template.yaml").write_text(_TEMPLATE, encoding="utf-8")
    (project / "data").mkdir(parents=True)
    (project / "project.yaml").write_text(
        "name: detached\ntemplate: templates/kit\nlocales: []\n"
        "formats:\n  - square\ndata: data/data.yaml\n",
        encoding="utf-8",
    )
    (project / "data" / "data.yaml").write_text("{}\n", encoding="utf-8")
    return project


def test_a_template_in_a_subdirectory_is_edited_where_it_lives(
    service: EditorService, tmp_path: Path
) -> None:
    """`detach` is the remedy this editor prescribes, so its result has to be editable.

    Two failures met here. The template was loaded with a file loader pointed at a *directory*,
    which reported "File not found" for a directory that plainly existed -- so the remedy for
    ARC-EDT-008 produced a project ARC-TPL-001 refused. And the write target was hard-coded to
    `template.yaml` at the project root, so had the load succeeded the edit would have landed in
    a file the project does not reference: six changes applied, `ok: true` returned, and nothing
    different on screen.
    """
    project = _project_with_a_nested_template(tmp_path)
    nested = project / "templates" / "kit" / "template.yaml"

    report = service.apply(
        _transaction(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_text", "layer_id": "title", "text": "EDITED"}],
        )
    )

    assert report.ok, [d.model_dump() for d in report.diagnostics]
    assert "EDITED" in nested.read_text(encoding="utf-8"), "the pinned template was not edited"
    assert not (project / "template.yaml").exists(), (
        "the edit created a second template at the project root that nothing renders"
    )
    assert [c.path for c in report.changed] == ["templates/kit/template.yaml"]


def test_a_malformed_transaction_hides_none_of_its_problems(service: EditorService) -> None:
    """Reporting a subset makes the caller fix what it can see, then start again.

    An agent that had corrected everything reported was told only "and 1 more", and spent
    another round trip rediscovering the one error the message had dropped.
    """
    report = service.apply(
        {
            "command_id": "11111111-1111-4111-8111-111111111111",
            "project_path": "/tmp/x",
            "base_project_revision": "a" * 64,
            "actor": {"id": "a"},
            "commands": [
                {"kind": "translate", "layer_id": "one"},
                {"kind": "resize", "layer_id": "two"},
                {"kind": "reorder", "layer_ids": ["three"]},
            ],
        }
    )

    detail = " ".join(d.message for d in report.diagnostics)
    assert "more" not in detail.split("nothing was executed.")[-1], detail
    for command_index in ("commands.0", "commands.1", "commands.2"):
        assert command_index in detail, f"{command_index} missing from: {detail}"


# ---------------------------------------------------------------------- editing one format


def _scoped(
    project: Path, base: str, commands: list[dict[str, Any]], *, format_name: str | None = "story"
) -> dict[str, Any]:
    """A transaction asking for a format-only write, validated against that format."""
    transaction = _transaction(project, base, commands)
    transaction["target"] = {"format": format_name}
    transaction["scope"] = "format"
    return transaction


def _format_patch(template_file: Path, format_name: str) -> Any:
    raw = load_yaml(template_file)
    return raw["formats"][format_name].get("patch")


def test_scope_defaults_to_shared_and_shared_edits_the_authored_node(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """Every existing caller omits `scope`, so the default has to be the behaviour they had."""
    transaction = _transaction(
        project,
        _revision(tmp_path, project),
        [{"kind": "set_text", "layer_id": "title", "text": "New"}],
    )
    assert SemanticTransaction.model_validate(transaction).scope == "shared"
    transaction["scope"] = "shared"

    report = service.apply(transaction)

    assert report.ok, [d.model_dump() for d in report.diagnostics]
    raw = load_yaml(project / "template.yaml")
    assert raw["root"]["children"][1]["text"] == "New"
    assert all("patch" not in spec for spec in raw["formats"].values())
    assert [(c.path, c.location) for c in report.changed] == [("template.yaml", None)]
    assert report.inverse is not None and report.inverse.scope == "shared"


def test_scope_format_writes_a_format_patch_and_leaves_the_shared_node_alone(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """`target` says what to validate against; `scope: format` asks for a format-only write.

    An assistant sent `target: {format: story}` expecting a story-only change. The engine
    applied it to the shared node, changed every format, and returned ok. With the explicit
    scope the command becomes a `set` op in `formats.story.patch`, so the square keeps the
    authored value, and the report says where the write landed.
    """
    base = _revision(tmp_path, project)

    report = service.apply(
        _scoped(
            project,
            base,
            [
                {
                    "kind": "set_property",
                    "layer_id": "title",
                    "keypath": "style.font_size",
                    "value": "40pt",
                }
            ],
        )
    )

    assert report.ok, [d.model_dump() for d in report.diagnostics]
    template = project / "template.yaml"
    raw = load_yaml(template)
    assert raw["root"]["children"][1]["style"]["font_size"] == "24pt", "the shared node changed"
    assert _format_patch(template, "story") == [
        {"set": "nodes.title.style.font_size", "value": "40pt"}
    ]
    assert "patch" not in raw["formats"]["square"]
    text = template.read_text(encoding="utf-8")
    assert "# a comment that must survive editing" in text, "round-trip must keep comments"
    assert text.index("formats:") < text.index("root:"), "round-trip must keep key order"
    assert [(c.path, c.location) for c in report.changed] == [
        ("template.yaml", "formats.story.patch")
    ]
    assert report.changed_layer_ids == ["title"]
    assert report.inverse is not None
    assert report.inverse.scope == "format"
    assert report.inverse.target.format == "story"
    undo = report.inverse.commands[0]
    assert undo.kind == "set_property"
    assert undo.keypath == "style.font_size"  # type: ignore[union-attr]
    # The override did not exist before, so undoing drops it rather than writing a value.
    assert undo.remove is True  # type: ignore[union-attr]


def test_scope_format_replaces_an_existing_override_rather_than_appending(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    def scoped(base: str, value: str) -> dict[str, Any]:
        return _scoped(
            project,
            base,
            [
                {
                    "kind": "set_property",
                    "layer_id": "title",
                    "keypath": "style.font_size",
                    "value": value,
                }
            ],
        )

    first = service.apply(scoped(_revision(tmp_path, project), "40pt"))
    assert first.ok and first.project_revision is not None
    second = service.apply(scoped(first.project_revision, "44pt"))

    assert second.ok, [d.model_dump() for d in second.diagnostics]
    assert _format_patch(project / "template.yaml", "story") == [
        {"set": "nodes.title.style.font_size", "value": "44pt"}
    ]
    # Undoing the second edit restores the first override, not the shared value.
    assert second.inverse is not None
    undo = second.inverse.commands[0]
    assert undo.kind == "set_property"
    assert undo.value == "40pt"  # type: ignore[union-attr]
    assert undo.remove is False  # type: ignore[union-attr]


def test_a_format_scoped_edit_round_trips_through_undo_redo_and_its_inverse(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """History must treat a format-scoped transaction exactly like a shared one."""
    template = project / "template.yaml"
    before = template.read_bytes()
    applied = service.apply(
        _scoped(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_text", "layer_id": "title", "text": "Story headline"}],
        )
    )
    assert applied.ok, [d.model_dump() for d in applied.diagnostics]
    after = template.read_bytes()
    assert after != before
    assert _format_patch(template, "story") == [
        {"set": "nodes.title.text", "value": "Story headline"}
    ]

    undone = service.undo(project)
    assert undone.ok, undone.diagnostics
    assert template.read_bytes() == before
    assert service.history(project).can_redo

    redone = service.redo(project)
    assert redone.ok, redone.diagnostics
    assert template.read_bytes() == after
    assert redone.project_revision == applied.project_revision

    # The engine-authored inverse is executable in its own right and drops the override.
    assert applied.inverse is not None
    reverted = service.apply(applied.inverse.model_dump(mode="json"))
    assert reverted.ok, [d.model_dump() for d in reverted.diagnostics]
    raw = load_yaml(template)
    assert "patch" not in raw["formats"]["story"], "an empty patch list must not linger"
    assert raw["root"]["children"][1]["text"] == "Old headline"


def test_geometry_under_scope_format_builds_on_the_formats_effective_values(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """A second drag in the story moves on from where the story left the badge, not from the
    shared position, and the two drags collapse into one override."""

    def drag(base: str, dx: float, dy: float) -> dict[str, Any]:
        return _scoped(
            project,
            base,
            [{"kind": "translate", "layer_ids": ["badge"], "dx_pt": dx, "dy_pt": dy}],
        )

    first = service.apply(drag(_revision(tmp_path, project), 12.0, -6.0))
    assert first.ok and first.project_revision is not None
    second = service.apply(drag(first.project_revision, 5.0, 2.0))

    assert second.ok, [d.model_dump() for d in second.diagnostics]
    assert _format_patch(project / "template.yaml", "story") == [
        {"set": "nodes.badge.transform", "value": {"translate": [17.0, -4.0]}}
    ]
    raw = load_yaml(project / "template.yaml")
    assert "transform" not in raw["root"]["children"][2], "the shared badge moved"


def test_resize_and_rotate_under_scope_format_write_the_narrowest_override(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """A field the authored node already has is overridden at that field; one it lacks is
    overridden at the nearest container the node does have."""
    report = service.apply(
        _scoped(
            project,
            _revision(tmp_path, project),
            [
                {"kind": "resize", "layer_id": "badge", "w_pt": 40.0, "h_pt": 20.0},
                {"kind": "rotate", "layer_id": "badge", "degrees": 30.0},
                {"kind": "set_visibility", "layer_id": "background", "visible": False},
            ],
        )
    )

    assert report.ok, [d.model_dump() for d in report.diagnostics]
    assert _format_patch(project / "template.yaml", "story") == [
        {"set": "nodes.badge.constraints.size.w", "value": "40pt"},
        {"set": "nodes.badge.constraints.size.h", "value": "20pt"},
        {"set": "nodes.badge.transform", "value": {"rotate": 30.0}},
        {"set": "nodes.background.visible", "value": False},
    ]
    assert report.changed_layer_ids == ["background", "badge"]


def test_scope_format_without_a_target_format_is_refused(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    before = (project / "template.yaml").read_bytes()

    report = service.apply(
        _scoped(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_text", "layer_id": "title", "text": "x"}],
            format_name=None,
        )
    )

    assert report.ok is False
    assert [d.code for d in report.diagnostics] == ["ARC-EDT-013"]
    assert (project / "template.yaml").read_bytes() == before


def test_scope_format_naming_a_format_the_template_lacks_is_refused(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    """Patching a format that does not exist would conjure a canvas-less format spec."""
    before = (project / "template.yaml").read_bytes()

    report = service.apply(
        _scoped(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_text", "layer_id": "title", "text": "x"}],
            format_name="billboard",
        )
    )

    assert report.ok is False
    assert [d.code for d in report.diagnostics] == ["ARC-EDT-013"]
    detail = " ".join(f"{d.message} {d.hint or ''}" for d in report.diagnostics)
    assert "billboard" in detail
    assert "square" in detail and "story" in detail, "the formats that exist must be named"
    assert (project / "template.yaml").read_bytes() == before


@pytest.mark.parametrize(
    "command",
    [
        {"kind": "reorder", "layer_id": "badge", "parent_id": "root", "index": 0},
        {"kind": "reparent", "layer_id": "badge", "parent_id": "root", "index": 0},
        {"kind": "delete", "layer_ids": ["badge"]},
        {"kind": "duplicate", "layer_id": "badge"},
        {"kind": "group", "layer_ids": ["title", "badge"], "group_id": "cluster"},
        {"kind": "splice_children", "parent_id": "root", "index": 0, "entries": []},
        {"kind": "set_display_name", "layer_id": "title", "display_name": "Headline"},
    ],
    ids=lambda command: str(command["kind"]),
)
def test_commands_that_cannot_be_scoped_to_one_format_are_refused(
    service: EditorService, project: Path, tmp_path: Path, command: dict[str, Any]
) -> None:
    """Structure is shared by construction, and a display name is project-wide UI metadata.
    Applying either under a format scope would be the silent shared write this fix removes."""
    before = (project / "template.yaml").read_bytes()

    report = service.apply(_scoped(project, _revision(tmp_path, project), [command]))

    assert report.ok is False
    assert [d.code for d in report.diagnostics] == ["ARC-EDT-014"]
    detail = " ".join(f"{d.message} {d.hint or ''}" for d in report.diagnostics)
    assert command["kind"] in detail
    assert "shared" in detail
    assert (project / "template.yaml").read_bytes() == before


def test_a_lock_holds_under_scope_format(
    service: EditorService, project: Path, tmp_path: Path
) -> None:
    from arcavex.kernel.api import LayerUIMetadata, ProjectUIMetadata

    projects = _projects(tmp_path)
    projects.save_ui_metadata(
        projects.load(project),
        ProjectUIMetadata(layers={"badge": LayerUIMetadata(locked=True)}),
    )
    before = (project / "template.yaml").read_bytes()

    report = service.apply(
        _scoped(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_visibility", "layer_id": "badge", "visible": False}],
        )
    )

    assert report.ok is False
    assert [d.code for d in report.diagnostics] == ["ARC-EDT-006"]
    assert (project / "template.yaml").read_bytes() == before


def test_scope_format_edits_the_formats_sidecar_of_a_split_template(
    service: EditorService, tmp_path: Path
) -> None:
    """A split template keeps `formats` in formats.yaml; the override has to land there.

    Writing a `formats:` section into template.yaml instead would define the section twice,
    which the loader refuses (ARC-TPL-097) -- a confusing failure for an edit that named
    nothing but a node and a format.
    """
    project = tmp_path / "split"
    (project / "data").mkdir(parents=True)
    head, _, rest = _TEMPLATE.partition("formats:\n")
    formats_block, _, tail = rest.partition("preview_data:")
    (project / "template.yaml").write_text(head + "preview_data:" + tail, encoding="utf-8")
    (project / "formats.yaml").write_text(textwrap.dedent(formats_block), encoding="utf-8")
    (project / "project.yaml").write_text(_PROJECT_MANIFEST, encoding="utf-8")
    (project / "data" / "data.yaml").write_text("{}\n", encoding="utf-8")
    template_before = (project / "template.yaml").read_bytes()
    sidecar_before = (project / "formats.yaml").read_bytes()

    report = service.apply(
        _scoped(
            project,
            _revision(tmp_path, project),
            [{"kind": "set_text", "layer_id": "title", "text": "Story headline"}],
        )
    )

    assert report.ok, [d.model_dump() for d in report.diagnostics]
    assert (project / "template.yaml").read_bytes() == template_before
    assert load_yaml(project / "formats.yaml")["story"]["patch"] == [
        {"set": "nodes.title.text", "value": "Story headline"}
    ]
    assert [(c.path, c.location) for c in report.changed] == [
        ("formats.yaml", "formats.story.patch")
    ]

    undone = service.undo(project)
    assert undone.ok, undone.diagnostics
    assert (project / "formats.yaml").read_bytes() == sidecar_before

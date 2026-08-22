"""Two real processes editing one project: what the desktop must survive when it is not alone.

Arcavex is local-first and multi-client by design — a desktop window, an MCP client driving an
assistant, and a CLI in a terminal are separate operating-system processes over the same files.
The unit suites prove the lock, the revision guard, and the staged writer individually. This
suite proves them *together*, against a second real process, because that composition is where
"nothing was changed" either holds or quietly stops holding.

Every test here asks the same question in a different shape: after the collision, is the project
still a project? A refusal is an acceptable outcome. A half-written template is not.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

_TEMPLATE = """\
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
preview_data: {}
root:
  type: group
  id: root
  children:
    - id: title
      type: text
      text: "Original headline"
      style: {font: Inter, font_size: 24pt, color: "#222222"}
      constraints:
        anchor: {top: parent.top+20px, left: parent.left+20px}
        size: {w: 80%, h: fit_content}
"""

_HOLD_THE_LOCK = """\
import sys, time
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from arcavex.services.editor.locking import editor_lock

with editor_lock(Path(sys.argv[1]), timeout=30.0):
    print("held", flush=True)
    time.sleep(60)
"""


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "collab"
    (root / "data").mkdir(parents=True)
    (root / "template.yaml").write_text(_TEMPLATE, encoding="utf-8")
    (root / "project.yaml").write_text(
        "name: collab\ntemplate: template.yaml\nlocales: []\n"
        "formats:\n  - square\ndata: data/data.yaml\n",
        encoding="utf-8",
    )
    (root / "data" / "data.yaml").write_text("{}\n", encoding="utf-8")
    return root


def _editor() -> Any:
    from arcavex.bootstrap import build_editor_service

    return build_editor_service()


def _revision(project: Path) -> str:
    from arcavex.services.project_snapshot import ProjectSnapshotService
    from arcavex.services.projects import ProjectService

    report = ProjectSnapshotService(ProjectService()).snapshot(project=project)
    assert report.project_revision is not None
    return report.project_revision


def _transaction(project: Path, text: str, revision: str, actor: str) -> dict[str, Any]:
    return {
        "command_id": str(uuid.uuid4()),
        "project_path": str(project.resolve()),
        "base_project_revision": revision,
        "actor": {"id": actor},
        "target": {"format": "square"},
        "commands": [{"kind": "set_text", "layer_id": "title", "text": text}],
    }


def _cli_apply(
    project: Path, payload: dict[str, Any], tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    """Apply a transaction from a genuinely separate process, as a terminal or an agent would."""
    file = tmp_path / f"{uuid.uuid4().hex}.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", "editor", "apply", str(file), "--json"],
        cwd=str(project),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _files(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


def _is_loadable(project: Path) -> bool:
    """The project still parses and loads — the bar every failure path must clear."""
    from arcavex.services.projects import ProjectService

    try:
        ProjectService().load(project)
    except Exception:  # noqa: BLE001 - any failure to load is the failure under test
        return False
    return True


def test_an_edit_composed_before_an_external_one_is_refused_and_names_the_file(
    project: Path, tmp_path: Path
) -> None:
    """The desktop's stale edit must not silently overwrite what the CLI just wrote.

    This is the ordinary collaboration accident: a window open on the left, an agent or a
    terminal editing on the right. The desktop composed against a revision that no longer
    exists, so the only honest answer is a conflict — and one that names *which* file moved,
    because "the project changed" is not something a person can act on.
    """
    stale = _revision(project)

    external = _cli_apply(
        project, _transaction(project, "Written by the CLI", stale, "cli"), tmp_path
    )
    assert external.returncode == 0, external.stderr

    report = _editor().apply(_transaction(project, "Written by the desktop", stale, "desktop"))

    assert report.ok is False
    assert report.conflict is not None
    assert [changed.path for changed in report.conflict.changed] == ["template.yaml"]
    # The CLI's text survives intact: a refused transaction writes nothing at all.
    assert "Written by the CLI" in (project / "template.yaml").read_text(encoding="utf-8")


def test_a_rebased_edit_after_the_conflict_succeeds(project: Path, tmp_path: Path) -> None:
    """The conflict is recoverable: re-read, re-compose, apply. Otherwise it is a dead end."""
    stale = _revision(project)
    first = _cli_apply(project, _transaction(project, "First", stale, "cli"), tmp_path)
    assert first.returncode == 0, first.stderr

    editor = _editor()
    assert editor.apply(_transaction(project, "Second", stale, "desktop")).ok is False

    rebased = editor.apply(_transaction(project, "Second", _revision(project), "desktop"))

    assert rebased.ok is True
    assert "Second" in (project / "template.yaml").read_text(encoding="utf-8")


def test_undo_pops_the_newest_entry_whichever_process_wrote_it(
    project: Path, tmp_path: Path
) -> None:
    """History belongs to the project, not to a process — so undo is shared, and ordered.

    The desktop and the CLI append to one on-disk history. Undo therefore reverses the most
    recent transaction whoever made it, which is the only ordering that stays coherent when the
    same project is open in two places: a per-process history would let each one undo into a
    state the other had already moved past.
    """
    editor = _editor()
    assert editor.apply(_transaction(project, "Desktop edit", _revision(project), "desktop")).ok

    external = _cli_apply(
        project, _transaction(project, "CLI moved on", _revision(project), "cli"), tmp_path
    )
    assert external.returncode == 0, external.stderr

    report = editor.undo(project)

    assert report.ok is True
    # Exactly one step back: the CLI's edit is reversed, the desktop's is untouched.
    template = (project / "template.yaml").read_text(encoding="utf-8")
    assert "Desktop edit" in template
    assert "CLI moved on" not in template


def test_undo_stops_rather_than_replaying_over_an_edit_it_never_saw(project: Path) -> None:
    """A file changed outside Arcavex closes the line instead of being overwritten.

    Undo restores recorded bytes. If someone edited template.yaml in a text editor, replaying
    those bytes would silently erase that work — so the project's revision no longer matching
    any history entry has to mean *stop*, not *proceed*.
    """
    editor = _editor()
    assert editor.apply(_transaction(project, "Desktop edit", _revision(project), "desktop")).ok

    hand_edited = (project / "template.yaml").read_text(encoding="utf-8").replace(
        "Desktop edit", "Typed straight into a text editor"
    )
    (project / "template.yaml").write_text(hand_edited, encoding="utf-8")

    report = editor.undo(project)

    assert report.ok is False
    assert any(d.code == "ARC-EDT-011" for d in report.diagnostics)
    assert "Typed straight into a text editor" in (project / "template.yaml").read_text(
        encoding="utf-8"
    )


def test_a_held_lock_makes_the_second_writer_wait_rather_than_interleave(
    project: Path, tmp_path: Path
) -> None:
    """Two writers, one lock: the loser waits and is told why. Never both inside at once."""
    from arcavex.services.editor.locking import editor_lock

    editor = _editor()
    revision = _revision(project)

    with editor_lock(project, timeout=30.0):
        started = time.monotonic()
        blocked = _cli_apply(project, _transaction(project, "Waited", revision, "cli"), tmp_path)
        waited = time.monotonic() - started

    assert blocked.returncode != 0
    report = json.loads(blocked.stdout)
    assert any(d["code"] == "ARC-EDT-001" for d in report["diagnostics"])
    # It waited for the lock rather than failing instantly: contention is survivable, not fatal.
    assert waited >= 1.0
    assert "Original headline" in (project / "template.yaml").read_text(encoding="utf-8")

    # Once the lock is free the same edit goes through, so the refusal was about timing alone.
    assert editor.apply(_transaction(project, "Waited", _revision(project), "cli")).ok is True


def test_a_malformed_template_is_refused_without_being_rewritten(project: Path) -> None:
    """A source file someone broke by hand must be reported, not partially repaired."""
    from arcavex.kernel.diagnostics import DiagnosticError

    (project / "template.yaml").write_text("root: [this: is not: a template\n", encoding="utf-8")
    before = _files(project)

    try:
        report = _editor().apply(_transaction(project, "Anything", "0" * 64, "desktop"))
        assert report.ok is False
    except DiagnosticError as error:
        assert error.diagnostics

    assert {name: data for name, data in _files(project).items() if name in before} == before


def test_an_edit_refused_by_validation_leaves_every_file_byte_identical(project: Path) -> None:
    """Rollback is the whole promise of the staged writer: a refused edit is a no-op on disk."""
    before = _files(project)

    transaction = _transaction(project, "irrelevant", _revision(project), "desktop")
    transaction["commands"] = [{"kind": "delete", "layer_ids": ["root"]}]

    report = _editor().apply(transaction)

    assert report.ok is False
    assert {name: data for name, data in _files(project).items() if name in before} == before
    assert _is_loadable(project)


def test_the_project_survives_a_writer_killed_mid_transaction(project: Path) -> None:
    """A process that dies holding the lock must not leave the project locked forever.

    This is the sidecar-death case the desktop actually faces: the engine is a child process, and
    a crash during a command is a normal event rather than an exotic one. The next writer has to
    get in again — after the abandonment threshold — over an intact project.
    """
    from arcavex.services.editor.locking import editor_lock

    killer = subprocess.Popen(  # noqa: S603 - a fixed interpreter and a literal script
        [
            sys.executable,
            "-c",
            _HOLD_THE_LOCK,
            str(project),
            str(Path(__file__).resolve().parents[2] / "src"),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert killer.stdout is not None
        assert killer.stdout.readline().strip() == "held"
    finally:
        killer.kill()
        killer.wait(timeout=30)

    # The lock file outlives the process; what matters is that a live writer gets in again.
    with editor_lock(project, timeout=30.0, stale_after=0.0):
        pass

    assert _is_loadable(project)
    assert "Original headline" in (project / "template.yaml").read_text(encoding="utf-8")

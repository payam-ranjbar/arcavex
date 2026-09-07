"""Editor parity over the JSON CLI: the surface a script or an AI without MCP edits through."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

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
      text: "CLI headline"
      style: {font: Inter, font_size: 24pt, color: "#222222"}
      constraints:
        anchor: {top: parent.top+20px, left: parent.left+20px}
        size: {w: 80%, h: fit_content}
"""


def _run_cli(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", *arguments],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "cli-project"
    (root / "data").mkdir(parents=True)
    (root / "template.yaml").write_text(_TEMPLATE, encoding="utf-8")
    (root / "project.yaml").write_text(
        "name: cli-project\ntemplate: template.yaml\nlocales: []\n"
        "formats:\n  - square\ndata: data/data.yaml\n",
        encoding="utf-8",
    )
    (root / "data" / "data.yaml").write_text("{}\n", encoding="utf-8")
    return root


def _snapshot_revision(project: Path) -> str:
    # In-process: the CLI exposes snapshots through MCP, not a subcommand, and this helper is
    # scaffolding for the transaction — the editor commands themselves run as real subprocesses.
    from arcavex.services.project_snapshot import ProjectSnapshotService
    from arcavex.services.projects import ProjectService

    report = ProjectSnapshotService(ProjectService()).snapshot(project=project)
    assert report.project_revision is not None
    return report.project_revision


def _transaction(project: Path, text: str) -> dict[str, Any]:
    return {
        "command_id": str(uuid.uuid4()),
        "project_path": str(project.resolve()),
        "base_project_revision": _snapshot_revision(project),
        "actor": {"id": "cli-e2e"},
        "target": {"format": "square"},
        "commands": [{"kind": "set_text", "layer_id": "title", "text": text}],
    }


def test_apply_undo_redo_and_history_through_the_json_cli(
    project: Path, tmp_path: Path
) -> None:
    payload = tmp_path / "transaction.json"
    payload.write_text(json.dumps(_transaction(project, "Edited by CLI")), encoding="utf-8")

    applied = _run_cli("editor", "apply", str(payload), "--json", cwd=project)
    assert applied.returncode == 0, applied.stderr
    report = json.loads(applied.stdout)
    assert report["ok"] is True
    assert report["inverse"] is not None
    assert "Edited by CLI" in (project / "template.yaml").read_text(encoding="utf-8")

    history = _run_cli("editor", "history", "--project", str(project), "--json", cwd=project)
    assert history.returncode == 0, history.stderr
    assert json.loads(history.stdout)["can_undo"] is True

    undone = _run_cli("editor", "undo", "--project", str(project), "--json", cwd=project)
    assert undone.returncode == 0, undone.stderr
    assert "CLI headline" in (project / "template.yaml").read_text(encoding="utf-8")

    redone = _run_cli("editor", "redo", "--project", str(project), "--json", cwd=project)
    assert redone.returncode == 0, redone.stderr
    assert "Edited by CLI" in (project / "template.yaml").read_text(encoding="utf-8")


def test_a_refused_transaction_exits_nonzero_with_a_json_report(
    project: Path, tmp_path: Path
) -> None:
    payload = tmp_path / "bad.json"
    transaction = _transaction(project, "irrelevant")
    transaction["commands"] = [{"kind": "delete", "layer_ids": ["no-such-layer"]}]
    payload.write_text(json.dumps(transaction), encoding="utf-8")

    result = _run_cli("editor", "apply", str(payload), "--json", cwd=project)

    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert any(d["code"] == "ARC-EDT-004" for d in report["diagnostics"])

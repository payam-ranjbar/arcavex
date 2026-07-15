"""CLI transcripts for the project/provenance commands (spec §6.1.2).

Drives the Typer app in-process via CliRunner with an isolated ``$ARCAVEX_HOME`` and asserts on
exit codes and machine-readable ``--json`` output — the contract clients depend on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcavex.clients.cli import app

REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO = REPO_ROOT / "examples" / "hello-poster"
runner = CliRunner()


@pytest.fixture()
def project_dir(arcavex_home: Path, tmp_path: Path) -> Path:
    """Publish the template and scaffold a project, returning the project directory."""
    pub = runner.invoke(
        app, ["template", "publish", str(HELLO), "--name", "poster", "--version", "1.0.0", "--json"]
    )
    assert pub.exit_code == 0, pub.output
    proj = tmp_path / "proj"
    new = runner.invoke(
        app, ["project", "new", str(proj), "--template", "poster@1.0.0", "--json"]
    )
    assert new.exit_code == 0, new.output
    return proj


def test_project_new_json(project_dir: Path) -> None:
    status = runner.invoke(app, ["status", "--project", str(project_dir), "--json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["ok"] and payload["template"] == "poster@1.0.0"
    assert payload["status"] == "draft" and payload["runs"] == 0


def test_render_list_rerun_diff_flow(project_dir: Path) -> None:
    render = runner.invoke(app, ["render", "--project", str(project_dir), "--json"])
    assert render.exit_code == 0, render.output
    run = json.loads(render.stdout)
    assert run["ok"] and run["run_id"] and len(run["outputs"]) == 2

    listed = runner.invoke(app, ["list-runs", "--project", str(project_dir), "--json"])
    assert listed.exit_code == 0
    assert len(json.loads(listed.stdout)["runs"]) == 1

    run_dir = run["run_dir"]
    rerun = runner.invoke(app, ["rerun", run_dir, "--json"])
    assert rerun.exit_code == 0, rerun.output
    rr = json.loads(rerun.stdout)
    assert rr["ok"] and rr["reproduced"] is True

    diff = runner.invoke(app, ["diff", run_dir, rr["run_dir"], "--json"])
    assert diff.exit_code == 0
    d = json.loads(diff.stdout)
    assert all(o["identical"] for o in d["outputs"]) and not d["metadata"]


def test_status_without_project_errors(arcavex_home: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["status", "--project", str(tmp_path)])
    assert result.exit_code == 1
    assert "ARC-PRJ-001" in result.output


def test_set_status(project_dir: Path) -> None:
    result = runner.invoke(
        app, ["project", "set-status", "approved", "--project", str(project_dir), "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "approved"

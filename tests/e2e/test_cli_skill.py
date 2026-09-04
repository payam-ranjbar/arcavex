"""`arcavex skill install`, as a person at a terminal meets it.

Drives the Typer app in-process with CliRunner; every destination is an explicit ``--path`` under
``tmp_path`` so the developer's own skill directories are never touched.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arcavex.clients.cli import app

runner = CliRunner()


def test_a_repeat_install_says_why_nothing_happened(tmp_path: Path) -> None:
    """The second run used to print "Nothing to do." and exit 1 with the reason hidden in --json.

    The refusal is a coded diagnostic (ARC-SKL-003, "pass --force"); a person re-running the
    command is exactly who needs to read it.
    """
    first = runner.invoke(app, ["skill", "install", "--path", str(tmp_path)])
    assert first.exit_code == 0, first.output
    assert (tmp_path / "arcavex-design-studio" / "SKILL.md").is_file()

    second = runner.invoke(app, ["skill", "install", "--path", str(tmp_path)])

    assert second.exit_code != 0
    assert "ARC-SKL-003" in second.output, second.output
    assert "--force" in second.output, second.output


def test_force_reinstalls_over_an_existing_copy(tmp_path: Path) -> None:
    runner.invoke(app, ["skill", "install", "--path", str(tmp_path)])
    marker = tmp_path / "arcavex-design-studio" / "SKILL.md"
    marker.write_text("stale", encoding="utf-8")

    forced = runner.invoke(app, ["skill", "install", "--path", str(tmp_path), "--force"])

    assert forced.exit_code == 0, forced.output
    assert marker.read_text(encoding="utf-8") != "stale"
    assert "Restart the assistant" in forced.output

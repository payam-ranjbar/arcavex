"""The frozen-CLI surface gate: help parsing and agreement with the live source CLI."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from arcavex.clients.cli import app

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = runpy.run_path(str(ROOT / "scripts" / "check_cli_surface.py"))
parse_help_commands = _SCRIPT["parse_help_commands"]
source_command_groups = _SCRIPT["source_command_groups"]

_PLAIN_HELP = """\
Usage: arcavex [OPTIONS] COMMAND [ARGS]...

Options:
  --version  Show the engine version and exit.
  --help     Show this message and exit.

Commands:
  render     Render a template to an image or PDF, or (no template) the current
             project's recorded runs.
  validate   Validate a template without rendering.
  list-runs  List recorded runs, newest first.
  doctor     Check the environment and engine version.
"""

_RICH_HELP = """\
╭─ Commands ─────────────────────────────────────────────────────────────╮
│ render     Render a template to an image or PDF, or (no template) the   │
│            current project's recorded runs.                             │
│ validate   Validate a template without rendering.                       │
│ list-runs  List recorded runs, newest first.                            │
╰────────────────────────────────────────────────────────────────────────╯
"""


def test_parse_click_help_commands() -> None:
    """Plain captured help (what a frozen subprocess emits) yields the command names."""
    assert parse_help_commands(_PLAIN_HELP) == {"render", "validate", "list-runs", "doctor"}


def test_parse_rich_help_commands() -> None:
    """An interactive Rich panel yields the same names, ignoring wrapped descriptions."""
    assert parse_help_commands(_RICH_HELP) == {"render", "validate", "list-runs"}


_SQUARE_HELP = """\
┌─ Commands ─────────────────────────────────────────────────────────────┐
│ render     Render a template to an image or PDF, or (no template) the   │
│            current project's runs.                                      │
│ validate   Validate a template without rendering.                       │
└────────────────────────────────────────────────────────────────────────┘
"""


def test_parse_square_panel_help_commands() -> None:
    """The 0.1.0 standalone's captured help uses square corners; it must parse the same."""
    assert parse_help_commands(_SQUARE_HELP) == {"render", "validate"}


def test_parser_detects_a_missing_command_group() -> None:
    """A build whose help omits a source group must not compare equal to the source."""
    captured = parse_help_commands(_PLAIN_HELP)
    assert captured != source_command_groups()
    assert source_command_groups() - captured


def test_parser_matches_the_live_source_cli() -> None:
    """The parser must agree with the real CLI, whatever Typer renders at import time."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert parse_help_commands(result.output) == source_command_groups()


def test_check_cli_surface_accepts_the_installed_executable() -> None:
    """The venv's own arcavex.exe is the shared reference; the gate must accept it."""
    exe = Path(sys.executable).with_name("arcavex.exe" if os.name == "nt" else "arcavex")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_cli_surface.py"), str(exe)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "matches source" in result.stdout

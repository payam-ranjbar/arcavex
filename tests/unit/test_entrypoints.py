"""Every spelling of "run the CLI" that a person or an assistant plausibly types must work."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["arcavex", "arcavex.clients.cli"])
def test_python_dash_m_runs_the_cli(module: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", module, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("arcavex "), completed.stdout

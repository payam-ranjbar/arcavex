"""Guards on the release gate itself.

A verification target that cannot fail is worse than no target: it reports green and stops
anyone from looking. `make contracts` ran `python -m importlinter.cli lint`, which dispatches
nothing — it exits 0 with empty output even against a deliberately broken contract, so the
architecture gate in `make verify` had never actually run. These tests fail if that form comes
back, and if the tool that replaced it ever goes quiet.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAKEFILE = _REPO_ROOT / "Makefile"

# The exact invocation that silently passes. Kept as a literal so the guard is unambiguous.
_NO_OP_FORM = "-m importlinter.cli"


def _recipe(target: str) -> list[str]:
    """Return the command lines of a Makefile target, with variables expanded."""
    text = _MAKEFILE.read_text(encoding="utf-8")
    variables = dict(re.findall(r"^(\w+)\s*:=\s*(.+)$", text, re.M))
    match = re.search(rf"^{target}:.*\n((?:\t.*\n)+)", text, re.M)
    assert match is not None, f"no recipe for target {target!r}"
    lines = []
    for raw in match.group(1).splitlines():
        line = raw.lstrip("\t")
        for name, value in variables.items():
            line = line.replace(f"$({name})", value)
        lines.append(line)
    return lines


def _lint_imports_executable() -> str | None:
    """Locate the import-linter console script inside the running interpreter's environment."""
    return shutil.which("lint-imports", path=str(Path(sys.executable).parent))


def test_contracts_target_does_not_use_the_no_op_form() -> None:
    for line in _recipe("contracts"):
        assert _NO_OP_FORM not in line, (
            "`python -m importlinter.cli lint` exits 0 without checking anything; "
            "the contracts gate must invoke the lint-imports console script"
        )


def test_makefile_forces_utf8_on_shelled_out_tools() -> None:
    """Box-drawing output is truncated by the console codepage on the reference platform."""
    text = _MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^export PYTHONIOENCODING\s*:=\s*utf-8$", text, re.M)


def test_import_linter_actually_reports_its_verdict() -> None:
    """The replacement must print a verdict, so a silent pass is visibly different from a pass."""
    executable = _lint_imports_executable()
    if executable is None:
        pytest.skip("import-linter console script not installed in this environment")
    completed = subprocess.run(
        [executable],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Contracts:" in completed.stdout, (
        "the contracts gate produced no verdict line; a target that prints nothing and exits 0 "
        f"is indistinguishable from a pass. stdout={completed.stdout!r}"
    )
    assert "0 broken" in completed.stdout


def test_the_no_op_form_is_still_the_no_op_it_was_diagnosed_as() -> None:
    """Pin the reason the target changed, so a future revert is understood rather than guessed.

    If a later import-linter release makes `-m importlinter.cli` dispatch properly, this test
    fails and the comment in the Makefile can be revisited on evidence.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    assert completed.stdout.strip() == "", (
        "`python -m importlinter.cli lint` now produces output; re-evaluate the Makefile comment"
    )

"""Guards on the verification targets themselves.

`make contracts` ran `python -m importlinter.cli lint`, which dispatches nothing: it exits 0
with empty output even against a deliberately broken contract. A target that cannot fail reports
green regardless of the state of the code, so these tests check that the gate still runs and
still speaks.
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

# The invocation that exits 0 without checking. A literal, so the guard is unambiguous.
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
    """Non-ASCII tool output is truncated by the Windows console codepage without this."""
    text = _MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^export PYTHONIOENCODING\s*:=\s*utf-8$", text, re.M)


def test_import_linter_actually_reports_its_verdict() -> None:
    """A silent exit 0 must be distinguishable from a checked pass."""
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
        f"the contracts gate produced no verdict line. stdout={completed.stdout!r}"
    )
    assert "0 broken" in completed.stdout


def test_only_one_module_drives_the_backend() -> None:
    """Every render path reaches the backend through `kernel.pipeline.layout_and_render`.

    The solve-then-render sequence determines the output bytes. A second call site can diverge
    from the first — a budget check on one path only, different RenderOptions — and two paths
    then disagree on a byte.
    """
    src = _REPO_ROOT / "src" / "arcavex"
    callers = {
        path.relative_to(src).as_posix()
        for path in src.rglob("*.py")
        if re.search(r"\.render\(\s*layout", path.read_text(encoding="utf-8"))
    }
    assert callers == {"kernel/pipeline.py"}, callers


def test_the_no_op_form_is_still_a_no_op() -> None:
    """Pins the premise of the Makefile comment: this form produces nothing.

    If a later import-linter release makes `-m importlinter.cli` dispatch, this fails and the
    comment can be revisited.
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


def test_solver_quantum_matches_the_ir_contract() -> None:
    """The solver's rounding step is the quantum consumers are told to tolerate.

    `kernel.api` sizes its geometry tolerance from `GEOMETRY_QUANTUM_PT`. If the solver rounded
    to a coarser step, exact-edge comparisons would start flipping on quantization noise.
    """
    from arcavex.builtin.layout_anchors.solver import _QUANT
    from arcavex.kernel.api import _GEOMETRY_EPS_PT
    from arcavex.kernel.ir.units import GEOMETRY_QUANTUM_PT

    assert _QUANT == 1.0 / GEOMETRY_QUANTUM_PT
    assert _GEOMETRY_EPS_PT > GEOMETRY_QUANTUM_PT

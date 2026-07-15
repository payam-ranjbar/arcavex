"""Packaged-install test (spec §8.5): the built wheel ships fonts and installs render-ready.

Builds the wheel with ``uv build`` into a temp directory and asserts the bundled fonts are inside
it (the packaging gap that would otherwise make an installed engine unable to shape text). The full
clean-venv install-and-render is exercised by the ``packaged-install`` CI job and captured in
``docs/packaged-install.md``; this test guards the wheel's *contents* fast and locally. It skips
gracefully where ``uv`` is unavailable so it never blocks a contributor without the build tool.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to build the wheel")
def test_wheel_bundles_fonts(tmp_path: Path) -> None:
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    wheels = list(tmp_path.glob("arcavex-*.whl"))
    assert wheels, "no wheel was produced"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
    fonts = [n for n in names if n.startswith("arcavex/_bundled/fonts/") and n.endswith(".ttf")]
    # Both the Latin (Inter) and the Farsi (Vazirmatn/Estedad) families must ship so the bilingual
    # poster shapes from an installed engine.
    families = {Path(n).name.split("-")[0] for n in fonts}
    assert {"Inter", "Vazirmatn"} <= families, f"missing bundled families: {sorted(families)}"

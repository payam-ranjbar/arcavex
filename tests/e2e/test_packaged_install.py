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


def _build_wheel(tmp_path: Path) -> list[str]:
    """Build the wheel into ``tmp_path`` and return its member names."""
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
        return archive.namelist()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to build the wheel")
def test_wheel_bundles_fonts(tmp_path: Path) -> None:
    names = _build_wheel(tmp_path)
    fonts = [n for n in names if n.startswith("arcavex/_bundled/fonts/") and n.endswith(".ttf")]
    # Both the Latin (Inter) and the Farsi (Vazirmatn/Estedad) families must ship so the bilingual
    # poster shapes from an installed engine.
    families = {Path(n).name.split("-")[0] for n in fonts}
    assert {"Inter", "Vazirmatn"} <= families, f"missing bundled families: {sorted(families)}"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to build the wheel")
def test_wheel_bundles_style_packs(tmp_path: Path) -> None:
    """The seeded style packs must ship, like the fonts they are styled against.

    Style packs were previously found only by walking up to a ``pyproject.toml`` marker, so an
    engine installed outside a source checkout silently resolved zero packs and every
    ``style: pop-art`` reference failed. Nothing errored at install time — the vocabulary just
    went missing — so this guards the wheel's contents the same way the fonts test does.
    """
    names = _build_wheel(tmp_path)
    packs = [n for n in names if n.startswith("arcavex/_bundled/styles/") and n.endswith(".yaml")]
    assert packs, f"no bundled style packs in the wheel: {sorted(names)[:20]}"
    assert any("pop-art" in n for n in packs), f"pop-art pack missing: {packs}"

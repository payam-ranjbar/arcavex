"""Drift and toolchain checks for generated desktop contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCHEMA_DIR = ROOT / "schemas" / "desktop"
CONTRACT_DIR = ROOT / "apps" / "desktop" / "src" / "contracts"
EXPORTER = ROOT / "scripts" / "export_desktop_schemas.py"
GENERATOR = ROOT / "scripts" / "generate_desktop_contracts.mjs"


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _export_check(schema_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(EXPORTER),
            "--check",
            "--schema-dir",
            str(schema_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.parametrize(
    "mutation",
    ["stale-schema", "stale-fixture", "missing-schema", "extra-schema"],
)
def test_export_check_detects_schema_drift_without_mutating_tracked_files(
    tmp_path: Path, mutation: str
) -> None:
    """Exporter check must reject every managed drift class without rewriting canonical files."""
    tracked_before = _snapshot(SCHEMA_DIR)
    candidate = tmp_path / "desktop"
    shutil.copytree(SCHEMA_DIR, candidate)

    if mutation == "stale-schema":
        path = candidate / "engine-handshake.schema.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "stale-fixture":
        path = candidate / "desktop-contract-fixtures.json"
        path.write_text(path.read_text(encoding="utf-8").replace("fixture", "stale", 1))
    elif mutation == "missing-schema":
        (candidate / "hit-test.schema.json").unlink()
    else:
        (candidate / "unexpected.schema.json").write_text("{}\n", encoding="utf-8")

    result = _export_check(candidate)

    assert result.returncode != 0, mutation
    assert _snapshot(SCHEMA_DIR) == tracked_before


def test_export_check_accepts_exact_exports_without_mutating_them(tmp_path: Path) -> None:
    """A byte-identical copied export must pass and remain byte-identical."""
    candidate = tmp_path / "desktop"
    shutil.copytree(SCHEMA_DIR, candidate)
    before = _snapshot(candidate)

    result = _export_check(candidate)

    assert result.returncode == 0, result.stderr
    assert _snapshot(candidate) == before


def test_generator_check_honors_output_directory_and_rejects_ts_drift(
    tmp_path: Path,
) -> None:
    """Generator check must compare a supplied copy rather than silently checking canonical TS."""
    tracked_before = _snapshot(CONTRACT_DIR)
    candidate = tmp_path / "contracts"
    shutil.copytree(CONTRACT_DIR, candidate)
    generated = candidate / "generated.ts"
    generated.write_bytes(generated.read_bytes() + b" ")

    result = subprocess.run(
        ["node", str(GENERATOR), "--check", "--output", str(candidate)],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert _snapshot(CONTRACT_DIR) == tracked_before


def test_desktop_node_engine_pin_matches_root_nvmrc_exactly() -> None:
    """A range pin could select a different Node runtime than the repository toolchain."""
    expected = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
    package = json.loads((ROOT / "apps" / "desktop" / "package.json").read_text())
    lock = json.loads((ROOT / "apps" / "desktop" / "package-lock.json").read_text())

    assert package["engines"]["node"] == expected
    assert lock["packages"][""]["engines"]["node"] == expected

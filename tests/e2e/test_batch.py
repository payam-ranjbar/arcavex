"""Batch determinism: parallel (process-pool) output must equal serial output (spec §8.1)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade

REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO = REPO_ROOT / "examples" / "hello-poster"


def _outputs_by_project(report) -> dict[str, str]:  # noqa: ANN001 - BatchReport
    out: dict[str, str] = {}
    for entry in report.entries:
        proj = Path(entry.project).name
        for o in entry.outputs:
            out[f"{proj}/{Path(o).name}"] = hashlib.sha256(Path(o).read_bytes()).hexdigest()
    return out


@pytest.mark.usefixtures("arcavex_home")
def test_batch_parallel_equals_serial(tmp_path: Path) -> None:
    facade = build_facade()
    facade.publish_template(HELLO, "poster", "1.0.0")
    for name in ("alpha", "beta", "gamma"):
        result = facade.create_project(tmp_path / "camp" / name, name, "poster@1.0.0")
        assert result.ok, result.diagnostics

    serial = facade.batch_render([str(tmp_path / "camp" / "*")], jobs=1)
    parallel = facade.batch_render([str(tmp_path / "camp" / "*")], jobs=4)

    assert serial.ok and parallel.ok
    assert serial.jobs == 1 and parallel.jobs == 4
    assert len(parallel.entries) == 3
    serial_hashes = _outputs_by_project(serial)
    parallel_hashes = _outputs_by_project(parallel)
    assert serial_hashes.keys() == parallel_hashes.keys()
    assert serial_hashes == parallel_hashes, "parallel batch bytes must equal serial batch bytes"

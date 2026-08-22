"""Races between real processes: the guarantees the editor lock and writer make under contention.

The unit suites prove each piece in isolation. This proves the composition against the actual
failure mode — several operating-system processes editing one project at once — which is the
normal condition of this product: the desktop, an MCP client, and the CLI are separate processes
by design, not by accident.
"""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import pytest

_CONTEXT = mp.get_context("spawn")

_WRITERS = 4
_ROUNDS = 8


def _contending_writer(root: str, writer_id: int, queue: mp.Queue) -> None:  # type: ignore[type-arg]
    """Repeatedly rewrite counter.yaml as read-increment-write under the editor lock."""
    from arcavex.services.editor.locking import editor_lock
    from arcavex.services.editor.transaction import StagedWrite, apply_staged_writes

    project = Path(root)
    try:
        for _ in range(_ROUNDS):
            with editor_lock(project, timeout=60.0):
                counter = project / "counter.yaml"
                value = int(counter.read_text(encoding="utf-8").split(":")[1])
                content = f"count: {value + 1}\n".encode()
                apply_staged_writes(
                    project, [StagedWrite(relative="counter.yaml", content=content)]
                )
        queue.put(("done", writer_id))
    except BaseException as error:  # noqa: BLE001 - reported to the parent for the assertion
        queue.put(("failed", f"{writer_id}: {error!r}"))


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "contended"
    root.mkdir()
    (root / "counter.yaml").write_text("count: 0\n", encoding="utf-8")
    return root


def test_concurrent_writers_never_lose_an_increment(project: Path) -> None:
    """Lost updates are the signature of a broken lock; the count must be exact.

    Each of the writers does read-increment-write, which is only correct if the lock really
    excludes every other process for the whole cycle. A single lost update means two writers
    were inside at once.
    """
    queue: mp.Queue = _CONTEXT.Queue()  # type: ignore[type-arg]
    writers = [
        _CONTEXT.Process(target=_contending_writer, args=(str(project), writer_id, queue))
        for writer_id in range(_WRITERS)
    ]
    for writer in writers:
        writer.start()

    outcomes = [queue.get(timeout=300) for _ in writers]
    for writer in writers:
        writer.join(timeout=60)

    failures = [detail for status, detail in outcomes if status == "failed"]
    assert not failures, failures
    final = (project / "counter.yaml").read_text(encoding="utf-8")
    assert final == f"count: {_WRITERS * _ROUNDS}\n"


def test_contention_leaves_no_staging_or_lock_residue(project: Path) -> None:
    queue: mp.Queue = _CONTEXT.Queue()  # type: ignore[type-arg]
    writers = [
        _CONTEXT.Process(target=_contending_writer, args=(str(project), writer_id, queue))
        for writer_id in range(2)
    ]
    for writer in writers:
        writer.start()
    for _ in writers:
        queue.get(timeout=300)
    for writer in writers:
        writer.join(timeout=60)

    working = project / ".arcavex"
    assert not (working / "project.lock").exists()
    assert not (working / "staging").exists()

"""The editor's exclusive claim on a project, across processes rather than only threads.

Arcavex Desktop, an MCP client, and a CLI invocation are three operating-system processes that can
all decide to write the same project at the same moment. A thread lock would not see the others,
so the guarantee has to live in the filesystem, and these tests spawn real processes to prove it.

The engine already had a project mutation lock. What the editor adds is a bounded wait and a coded
refusal: a mutation that cannot get the lock must fail as a diagnostic a user can read, never as an
opaque timeout and never by writing anyway.
"""

from __future__ import annotations

import multiprocessing as mp
import time
from pathlib import Path

import pytest

from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.editor.locking import editor_lock

# Spawned deliberately: it is the start method on Windows, and it proves the lock works between
# processes that share no memory rather than forked copies that do.
_CONTEXT = mp.get_context("spawn")


def _hold_then_report(root: str, hold_seconds: float, queue: mp.Queue) -> None:  # type: ignore[type-arg]
    """Take the lock, announce it, hold it, and release."""
    from arcavex.services.editor.locking import editor_lock as child_lock

    with child_lock(Path(root)):
        queue.put("held")
        time.sleep(hold_seconds)
    queue.put("released")


def _try_acquire(root: str, timeout: float, queue: mp.Queue) -> None:  # type: ignore[type-arg]
    """Report whether the lock could be taken within `timeout`, and how it failed if not."""
    from arcavex.kernel.diagnostics import DiagnosticError as ChildDiagnosticError
    from arcavex.services.editor.locking import editor_lock as child_lock

    try:
        with child_lock(Path(root), timeout=timeout):
            queue.put(("acquired", None))
    except ChildDiagnosticError as error:
        queue.put(("refused", error.diagnostics[0].code))


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def test_the_lock_is_exclusive_across_processes(project: Path) -> None:
    queue: mp.Queue = _CONTEXT.Queue()  # type: ignore[type-arg]
    holder = _CONTEXT.Process(target=_hold_then_report, args=(str(project), 2.0, queue))
    holder.start()
    try:
        assert queue.get(timeout=30) == "held"

        contender: mp.Queue = _CONTEXT.Queue()  # type: ignore[type-arg]
        second = _CONTEXT.Process(target=_try_acquire, args=(str(project), 0.4, contender))
        second.start()
        outcome, code = contender.get(timeout=30)
        second.join(timeout=30)

        assert outcome == "refused"
        assert code == "ARC-EDT-001"
    finally:
        holder.join(timeout=30)
        if holder.is_alive():  # pragma: no cover - only on a wedged child
            holder.terminate()


def test_the_lock_is_available_once_the_holder_releases_it(project: Path) -> None:
    queue: mp.Queue = _CONTEXT.Queue()  # type: ignore[type-arg]
    holder = _CONTEXT.Process(target=_hold_then_report, args=(str(project), 0.2, queue))
    holder.start()
    assert queue.get(timeout=30) == "held"
    assert queue.get(timeout=30) == "released"
    holder.join(timeout=30)

    contender: mp.Queue = _CONTEXT.Queue()  # type: ignore[type-arg]
    second = _CONTEXT.Process(target=_try_acquire, args=(str(project), 5.0, contender))
    second.start()
    outcome, _ = contender.get(timeout=30)
    second.join(timeout=30)

    assert outcome == "acquired"


def test_a_timeout_is_a_readable_refusal_not_a_raw_timeouterror(project: Path) -> None:
    """A wedged sidecar must produce something the diagnostics panel can render."""
    with editor_lock(project):
        # Re-entrant within one thread, so a nested acquire cannot be what times out here.
        with pytest.raises(DiagnosticError) as raised:
            _take_lock_in_another_thread(project, timeout=0.2)

    diagnostic = raised.value.diagnostics[0]
    assert diagnostic.code == "ARC-EDT-001"
    assert "lock" in diagnostic.message.lower()
    assert diagnostic.hint


def _take_lock_in_another_thread(project: Path, timeout: float) -> None:
    """Acquire from a thread that does not hold the re-entrant claim."""
    import threading

    failure: list[BaseException] = []

    def attempt() -> None:
        try:
            with editor_lock(project, timeout=timeout):
                pass
        except BaseException as error:  # noqa: BLE001 - re-raised on the calling thread
            failure.append(error)

    thread = threading.Thread(target=attempt)
    thread.start()
    thread.join(timeout=30)
    if failure:
        raise failure[0]


def test_an_abandoned_lock_is_reclaimed_rather_than_wedging_the_project(project: Path) -> None:
    """A process killed mid-edit leaves its lock file behind; the next writer must recover."""
    working = project / ".arcavex"
    working.mkdir()
    abandoned = working / "project.lock"
    abandoned.write_text("99999", encoding="ascii")
    # Backdate it well beyond the timeout the next acquirer will allow.
    old = time.time() - 600
    import os

    os.utime(abandoned, (old, old))

    with editor_lock(project, timeout=1.0):
        assert abandoned.exists()

    assert not abandoned.exists()


def test_the_lock_is_re_entrant_within_one_thread(project: Path) -> None:
    """One transaction may call helpers that also take the lock; that must not deadlock."""
    with editor_lock(project):
        with editor_lock(project):
            assert (project / ".arcavex" / "project.lock").exists()


def test_the_lock_refuses_a_linked_working_directory(project: Path, tmp_path: Path) -> None:
    """A junctioned .arcavex would put engine-managed state outside the project."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    working = project / ".arcavex"
    try:
        working.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - unprivileged Windows
        pytest.skip("creating a directory symlink requires privileges here")

    with pytest.raises(DiagnosticError) as raised:
        with editor_lock(project):
            pass

    assert raised.value.diagnostics[0].code == "ARC-PRJ-014"

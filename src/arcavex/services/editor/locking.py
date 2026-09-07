"""One writer at a time, across processes, with a refusal a person can act on.

Arcavex Desktop, an MCP client, and a CLI invocation are separate operating-system processes that
may all decide to write the same project. The engine already serializes project mutations through
``.arcavex/project.lock``; what the editor adds is a bounded wait and a coded diagnostic, because a
mutation that cannot get the lock has to fail visibly rather than as an opaque ``TimeoutError`` —
and must never fall back to writing anyway.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.project_locking import project_mutation_lock

#: Long enough to outlast a render another process is holding the lock through, short enough that
#: a wedged writer surfaces as a refusal within one interaction rather than appearing to hang.
DEFAULT_LOCK_TIMEOUT = 15.0

#: How old a lock must be before it is presumed abandoned. Deliberately far longer than the wait:
#: giving up quickly is a caller's choice, but declaring another process's live lock abandoned and
#: writing anyway is exactly the corruption the lock exists to prevent.
DEFAULT_STALE_AFTER = 300.0


@contextmanager
def editor_lock(
    root: Path,
    *,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
    stale_after: float = DEFAULT_STALE_AFTER,
) -> Iterator[None]:
    """Hold the project mutation lock, or raise a coded refusal.

    Re-entrant within a thread: a transaction may call helpers that take the lock again.

    Raises:
        DiagnosticError: ``ARC-EDT-001`` when the lock is held elsewhere for longer than
            ``timeout``, or ``ARC-PRJ-014`` when the project's working directory is unsafe.
    """
    try:
        with project_mutation_lock(root, timeout=timeout, stale_after=stale_after):
            yield
    except TimeoutError as error:
        raise DiagnosticError(
            diagnostic(
                "ARC-EDT-001",
                "Could not acquire the project mutation lock: another process is writing to "
                f"this project and did not release it within {timeout:g}s.",
                file=str(root / ".arcavex" / "project.lock"),
                hint=(
                    "Wait for the other editor, AI client, or CLI command to finish and retry. "
                    "If nothing is running, remove the stale .arcavex/project.lock file."
                ),
            )
        ) from error

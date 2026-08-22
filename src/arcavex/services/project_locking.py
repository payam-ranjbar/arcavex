"""Safe project-local mutation paths and the shared project mutation lock."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.fsutil import file_lock

_LOCK_STATE = threading.local()


@contextmanager
def project_mutation_lock(
    root: Path, *, timeout: float = 30.0, stale_after: float | None = None
) -> Iterator[None]:
    """Hold the one re-entrant cross-process lock for project-revision mutations.

    Raises:
        TimeoutError: when another process holds the lock for longer than ``timeout``. Callers
            that face a user translate this into a coded diagnostic; see
            :func:`arcavex.services.editor.locking.editor_lock`.
    """
    canonical_root = root.resolve()
    working = canonical_root / ".arcavex"
    ensure_project_path_safe(canonical_root, working)
    working.mkdir(exist_ok=True)
    ensure_project_path_safe(canonical_root, working)
    lock_path = working / "project.lock"

    held = getattr(_LOCK_STATE, "paths", set())
    if lock_path in held:
        yield
        return

    def validate() -> None:
        ensure_project_path_safe(canonical_root, working)
        ensure_project_path_safe(canonical_root, lock_path)

    with file_lock(lock_path, timeout=timeout, stale_after=stale_after, validate=validate):
        validate()
        _LOCK_STATE.paths = {*held, lock_path}
        try:
            yield
        finally:
            _LOCK_STATE.paths = held


def ensure_project_path_safe(root: Path, path: Path) -> None:
    """Reject links/junctions and any resolved component outside canonical ``root``."""
    canonical_root = root.resolve()
    lexical = Path(path)
    try:
        relative = lexical.relative_to(canonical_root)
    except ValueError as exc:
        raise _unsafe(path, "path is not lexically contained by the project") from exc

    current = canonical_root
    for part in relative.parts:
        current /= part
        if _is_link(current):
            raise _unsafe(current, "symlinks and directory junctions are not allowed")
        if current.exists() and not _resolves_inside(current, canonical_root):
            # A file another process is creating, deleting, or holding open at this exact
            # moment can transiently resolve through a short-name or unresolved fallback on
            # Windows and appear to escape. A real junction or symlink escape is *stable*, so
            # only a resolution that still escapes on a fresh look — for a path that still
            # exists — is refused. A vanished path escapes nothing.
            time.sleep(0.01)
            if current.exists() and not _resolves_inside(current, canonical_root):
                raise _unsafe(current, "resolved path leaves the project")


def _resolves_inside(path: Path, canonical_root: Path) -> bool:
    """Whether ``path`` resolves under the root, comparing case-insensitively on Windows."""
    try:
        resolved = path.resolve()
    except OSError:
        return True  # unreadable mid-transition; the caller re-checks
    root = os.path.normcase(str(canonical_root))
    candidate = os.path.normcase(str(resolved))
    return candidate == root or candidate.startswith(root + os.sep)


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _unsafe(path: Path, detail: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-PRJ-014",
            f"Unsafe project working path: {detail}",
            file=str(path),
            hint=(
                "Replace linked .arcavex, pending, or proposal record paths with real "
                "directories/files contained by the canonical project root."
            ),
        )
    )

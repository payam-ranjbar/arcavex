"""Safe project-local mutation paths and the shared project mutation lock."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.fsutil import file_lock

_LOCK_STATE = threading.local()


@contextmanager
def project_mutation_lock(root: Path) -> Iterator[None]:
    """Hold the one re-entrant cross-process lock for project-revision mutations."""
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

    with file_lock(lock_path, validate=validate):
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
        if current.exists():
            resolved = current.resolve()
            try:
                resolved.relative_to(canonical_root)
            except ValueError as exc:
                raise _unsafe(current, "resolved path leaves the project") from exc


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

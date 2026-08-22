"""Staged, validated, atomic multi-file writes: all of a transaction lands, or none of it.

A semantic transaction can touch several files — the template, a data file, an override patch.
The dangerous state is the partial one: template.yaml rewritten, the override not yet, and a crash
between them leaves a project no revision has ever described and no validator ever approved. The
protocol here makes that state unreachable:

1. **Stage.** Every new file content is written under ``.arcavex/staging/<run>/`` inside the
   project, so staged bytes are on the same filesystem as their destinations and ``os.replace``
   stays atomic.
2. **Validate.** The caller's validator sees a complete overlay of the project with the staged
   changes applied. A refusal at this point has cost nothing: the live project was never touched.
3. **Replace with rollback.** Each destination is backed up, then atomically replaced. If any
   replacement fails, every completed one is restored from its backup before the error surfaces.

This module knows nothing about commands. It is handed final file contents; deciding what those
contents should be is the executor's job (Task 5).
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.kernel.editor import ChangedPath
from arcavex.services.project_locking import ensure_project_path_safe


@dataclass(frozen=True)
class StagedWrite:
    """One file's complete new content, or ``None`` to delete it."""

    relative: str
    content: bytes | None


def apply_staged_writes(
    root: Path,
    writes: list[StagedWrite],
    *,
    validate: Callable[[Path], None] | None = None,
) -> list[ChangedPath]:
    """Apply ``writes`` to the project atomically and return what changed.

    Args:
        root: The canonical project directory.
        writes: Complete new content per project-relative path; ``None`` deletes.
        validate: Called with a staged overlay of the whole project before anything live is
            touched. Raising from it aborts the transaction with the project byte-identical.

    Returns:
        One :class:`ChangedPath` per write, describing whether it created, modified, or deleted.

    Raises:
        DiagnosticError: ``ARC-PRJ-014`` for a path outside the project or under ``.arcavex``,
            whatever the validator raises, or ``ARC-EDT-002`` when a replacement failed and the
            completed ones were rolled back.
    """
    canonical = root.resolve()
    destinations = _checked_destinations(canonical, writes)

    staging = canonical / ".arcavex" / "staging" / uuid.uuid4().hex
    backups = staging / "_backups"
    try:
        overlay = staging / "overlay"
        _build_overlay(canonical, overlay, writes)
        if validate is not None:
            validate(overlay)

        changed = _plan_changes(canonical, writes)
        _replace_all(canonical, destinations, writes, overlay, backups)
        return changed
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        # Leave no trace at all: an empty staging/ directory would read as an interrupted edit.
        for parent in (staging.parent, staging.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break


# ------------------------------------------------------------------------------------ internals


def _checked_destinations(canonical: Path, writes: list[StagedWrite]) -> list[Path]:
    """Resolve every destination, refusing escapes and engine-managed state."""
    destinations: list[Path] = []
    for write in writes:
        relative = Path(write.relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise _unsafe(write.relative, "path is not contained by the project")
        if relative.parts and relative.parts[0] == ".arcavex":
            # History, the queue, and locks live here. A transaction that could write them could
            # forge its own history or release someone else's lock.
            raise _unsafe(write.relative, "engine-managed state cannot be edited by a transaction")
        destination = canonical / relative
        ensure_project_path_safe(canonical, destination)
        destinations.append(destination)
    return destinations


def _build_overlay(canonical: Path, overlay: Path, writes: list[StagedWrite]) -> None:
    """Materialize the project as it would look after the writes, for validation.

    Copied per file rather than as a whole tree: outputs and caches can dwarf the source, and the
    validator only needs source files. ``.arcavex`` and ``outputs`` are never part of an overlay.
    """
    overlay.mkdir(parents=True)
    for path in canonical.rglob("*"):
        relative = path.relative_to(canonical)
        if relative.parts and relative.parts[0] in {".arcavex", "outputs"}:
            continue
        target = overlay / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    for write in writes:
        target = overlay / write.relative
        if write.content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(write.content)


def _plan_changes(canonical: Path, writes: list[StagedWrite]) -> list[ChangedPath]:
    changes: list[ChangedPath] = []
    for write in writes:
        existed = (canonical / write.relative).is_file()
        if write.content is None:
            change = "deleted"
        elif existed:
            change = "modified"
        else:
            change = "created"
        changes.append(ChangedPath(path=Path(write.relative).as_posix(), change=change))
    return changes


def _replace_file(source: Path, destination: Path) -> None:
    """The one primitive a test can break to prove rollback works."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


def _replace_all(
    canonical: Path,
    destinations: list[Path],
    writes: list[StagedWrite],
    overlay: Path,
    backups: Path,
) -> None:
    """Back up and replace every destination; on any failure, restore what was completed."""
    completed: list[tuple[Path, Path | None]] = []
    backups.mkdir(parents=True)
    try:
        for index, (write, destination) in enumerate(zip(writes, destinations, strict=True)):
            backup: Path | None = None
            if destination.is_file():
                backup = backups / str(index)
                shutil.copy2(destination, backup)

            if write.content is None:
                destination.unlink(missing_ok=True)
            else:
                staged = overlay / write.relative
                _replace_file(staged, destination)
            completed.append((destination, backup))
    except OSError as error:
        for destination, backup in reversed(completed):
            if backup is not None:
                shutil.copy2(backup, destination)
            else:
                destination.unlink(missing_ok=True)
        raise DiagnosticError(
            diagnostic(
                "ARC-EDT-002",
                f"A transaction write failed and was rolled back: {error}. The project is "
                "unchanged.",
                file=str(canonical),
                hint="Check disk space and file permissions, then retry the edit.",
            )
        ) from error


def _unsafe(relative: str, detail: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-PRJ-014",
            f"Unsafe project working path: {detail}",
            file=relative,
            hint="Edit only source files inside the project directory.",
        )
    )

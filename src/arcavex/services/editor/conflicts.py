"""The revision guard: refuse a stale mutation and name the files that moved.

A transaction carries the project revision it was composed against. Under the mutation lock the
executor takes a fresh snapshot; if the revisions differ, the mutation must be refused — but
"someone changed the project" is not something a person can resolve. The conflict they can resolve
names files: *data/event.yaml changed underneath you*.

Naming files requires the manifest the stale revision described, which a hash alone cannot
reconstruct. So every snapshot and successful transaction remembers its manifest under
``.arcavex/manifests/<revision>.json``, and the guard diffs the fresh manifest against the
remembered one. A base revision nothing remembered still conflicts — it reports the two revisions
with an empty changed list rather than guessing.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arcavex.kernel.api import RevisionManifestEntry
from arcavex.kernel.editor import ChangedPath, ConflictDetail

#: Remembered manifests kept per project. Conflicts are only nameable against recent revisions,
#: which is the case that matters: a base older than this is stale beyond file-level explanation.
MANIFEST_MEMORY_LIMIT = 32


class _StoredManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: list[RevisionManifestEntry]


def _directory(root: Path) -> Path:
    return root.resolve() / ".arcavex" / "manifests"


def remember_manifest(
    root: Path, revision: str, manifest: list[RevisionManifestEntry]
) -> None:
    """Record the manifest a revision described, so a later conflict can name files."""
    from arcavex.services.fsutil import atomic_write_bytes

    directory = _directory(root)
    payload = _StoredManifest(revision=revision, entries=manifest)
    atomic_write_bytes(
        directory / f"{revision}.json",
        payload.model_dump_json(indent=2).encode("utf-8") + b"\n",
    )

    stored = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for stale in stored[: max(0, len(stored) - MANIFEST_MEMORY_LIMIT)]:
        stale.unlink(missing_ok=True)


def conflict_between(
    root: Path,
    base_revision: str,
    fresh_revision: str,
    *,
    fresh_manifest: list[RevisionManifestEntry],
) -> ConflictDetail | None:
    """Return the conflict a stale base revision represents, or ``None`` when it is current."""
    if base_revision == fresh_revision:
        return None

    remembered = _recall(root, base_revision)
    changed: list[ChangedPath] = []
    if remembered is not None:
        old = {entry.path: entry.sha256 for entry in remembered}
        new = {entry.path: entry.sha256 for entry in fresh_manifest}
        for path in sorted(old.keys() | new.keys()):
            if path not in new:
                changed.append(ChangedPath(path=path, change="deleted"))
            elif path not in old:
                changed.append(ChangedPath(path=path, change="created"))
            elif old[path] != new[path]:
                changed.append(ChangedPath(path=path, change="modified"))

    return ConflictDetail(
        expected_project_revision=base_revision,
        actual_project_revision=fresh_revision,
        changed=changed,
    )


def _recall(root: Path, revision: str) -> list[RevisionManifestEntry] | None:
    path = _directory(root) / f"{revision}.json"
    try:
        stored = _StoredManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError):
        return None
    return stored.entries

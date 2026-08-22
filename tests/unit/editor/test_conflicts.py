"""The revision guard: a stale mutation is refused with the files that actually moved.

"Someone changed the project" is not actionable. The conflict a person can resolve names the
files: *data/event.yaml changed underneath you*. Naming them requires the manifest the stale
revision described, so every snapshot and transaction remembers its manifest under
``.arcavex/manifests/``, and the guard diffs the fresh manifest against the remembered one.

A revision nothing remembered still conflicts — it just cannot name files, and it says so by
returning an empty changed list rather than guessing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.kernel.api import RevisionManifestEntry
from arcavex.services.editor.conflicts import (
    MANIFEST_MEMORY_LIMIT,
    conflict_between,
    remember_manifest,
)

_BASE = "a1" * 32
_FRESH = "b2" * 32


def _entry(path: str, sha: str) -> RevisionManifestEntry:
    return RevisionManifestEntry(path=path, sha256=sha * 32, bytes=10)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def test_a_matching_revision_is_no_conflict(project: Path) -> None:
    assert conflict_between(project, _BASE, _BASE, fresh_manifest=[]) is None


def test_a_stale_revision_names_the_files_that_changed(project: Path) -> None:
    remember_manifest(
        project, _BASE, [_entry("template.yaml", "aa"), _entry("data/event.yaml", "bb")]
    )

    conflict = conflict_between(
        project,
        _BASE,
        _FRESH,
        fresh_manifest=[
            _entry("template.yaml", "aa"),  # unchanged
            _entry("data/event.yaml", "cc"),  # modified
            _entry("overrides/square.patch.yaml", "dd"),  # created
        ],
    )

    assert conflict is not None
    assert conflict.expected_project_revision == _BASE
    assert conflict.actual_project_revision == _FRESH
    assert {(c.path, c.change) for c in conflict.changed} == {
        ("data/event.yaml", "modified"),
        ("overrides/square.patch.yaml", "created"),
    }


def test_a_deleted_file_is_reported_as_deleted(project: Path) -> None:
    remember_manifest(project, _BASE, [_entry("data/event.yaml", "bb")])

    conflict = conflict_between(project, _BASE, _FRESH, fresh_manifest=[])

    assert conflict is not None
    assert [(c.path, c.change) for c in conflict.changed] == [("data/event.yaml", "deleted")]


def test_an_unremembered_base_still_conflicts_but_names_nothing(project: Path) -> None:
    conflict = conflict_between(
        project, _BASE, _FRESH, fresh_manifest=[_entry("template.yaml", "aa")]
    )

    assert conflict is not None
    assert conflict.changed == []


def test_the_manifest_memory_is_bounded(project: Path) -> None:
    for index in range(MANIFEST_MEMORY_LIMIT + 10):
        revision = f"{index:02x}" * 32
        remember_manifest(project, revision, [_entry("template.yaml", "aa")])

    stored = list((project / ".arcavex" / "manifests").glob("*.json"))
    assert len(stored) <= MANIFEST_MEMORY_LIMIT


def test_remembering_the_same_revision_twice_is_idempotent(project: Path) -> None:
    remember_manifest(project, _BASE, [_entry("template.yaml", "aa")])
    remember_manifest(project, _BASE, [_entry("template.yaml", "aa")])

    stored = list((project / ".arcavex" / "manifests").glob("*.json"))
    assert len(stored) == 1

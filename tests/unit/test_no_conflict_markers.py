"""No tracked file may carry a merge-conflict marker.

Twenty commits on one branch shipped `<<<<<<< HEAD` inside `docs/diagnostics.md`, through a full
green suite each time, because every gate reads that file with a regex that skips lines it does not
recognise: the coded-diagnostics test matched the rows either side of the markers and never saw
them. A resolution script that handled one hunk and a `git add` that trusted it were enough. Nothing
downstream can catch this, so it is checked directly and cheaply.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
#: Written so this file's own examples do not match: the marker, then its separator.
_MARKERS = ("<" * 7 + " ", ">" * 7 + " ", "|" + "|" * 6 + " ")
_CONFLICT = ("<" * 7 + " ", "=" * 7, ">" * 7 + " ")
_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".ttf", ".otf", ".ico", ".woff", ".woff2",
    ".zip", ".gz", ".exe", ".dll", ".so", ".dylib", ".pyc",
}


def _tracked_text_files() -> list[Path]:
    """Every file git tracks that is worth reading as text."""
    listed = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    ).stdout.split("\0")
    return [
        REPO / name
        for name in listed
        if name and Path(name).suffix.lower() not in _BINARY_SUFFIXES
    ]


def test_git_tracks_the_repository() -> None:
    """A guard on an empty listing: the check below would pass vacuously."""
    assert len(_tracked_text_files()) > 100


@pytest.mark.parametrize("marker", _CONFLICT)
def test_no_tracked_file_contains_a_conflict_marker(marker: str) -> None:
    offenders: list[str] = []
    for path in _tracked_text_files():
        if path == Path(__file__):
            continue  # this file names the markers on purpose
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if line.startswith(marker) and (marker != "=" * 7 or line.rstrip() == marker):
                offenders.append(f"{path.relative_to(REPO)}:{number}")
    assert not offenders, f"conflict markers left in: {offenders}"

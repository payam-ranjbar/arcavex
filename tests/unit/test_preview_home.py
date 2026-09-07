"""Previews must land in the home the engine reports, not a second default of their own.

`doctor` promises one self-consistent home: "the single source of truth the library, the cache
check, and every other reader use ... never two disagreeing defaults in the same run". The facade
had its own fallback, so with `ARCAVEX_HOME` unset it wrote previews under the OS temp directory
while `doctor` and the desktop handshake both reported `~/.arcavex/cache/preview`.

Nothing in the engine noticed, because a preview is addressed by the path the report returns. It
surfaced in Arcavex Desktop, which resolves rendered images against the engine's reported cache and
refused every preview as written outside anywhere it can serve from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex import bootstrap

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "basic-poster"


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home the engine defaults to, with no ARCAVEX_HOME to paper over the difference."""
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.delenv("ARCAVEX_HOME", raising=False)
    monkeypatch.setattr(bootstrap, "home_dir", lambda: root)
    return root


def test_project_previews_are_written_under_the_reported_home(home: Path, tmp_path: Path) -> None:
    facade = bootstrap.build_facade()
    # A template path rather than a library reference: this is about where output goes, and a
    # published template would drag the library's own home resolution into the assertion.
    created = facade.create_project(tmp_path / "proj", "demo", str(FIXTURE))
    assert created.ok, created.diagnostics

    report = facade.preview_project(project=tmp_path / "proj", formats=["square"])
    assert report.ok, report.diagnostics
    assert report.previews and report.previews[0].output_path

    written = Path(report.previews[0].output_path)
    assert written.is_file()
    assert written.parent == home / "cache" / "preview", (
        f"preview went to {written.parent}, but the engine reports {home / 'cache' / 'preview'}"
    )

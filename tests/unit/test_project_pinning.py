"""How a project records the location of a template that lives outside it.

A relative pin keeps a project and its template relocatable as one tree. Windows has a case where
no relative path exists at all: two drives. `os.path.relpath` raises rather than inventing one, and
that ValueError reached the user as `ARC-INT-999 internal engine error` for an ordinary
arrangement — work on the data drive, the engine's examples on the system drive. CI found it
because its checkout is on `D:` and its temp directory on `C:`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from arcavex import bootstrap
from arcavex.services import projects as projects_module

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "basic-poster"


def test_a_template_beside_the_project_is_pinned_relatively(
    tmp_path: Path, arcavex_home: Path
) -> None:
    """The ordinary case, which keeps the pair movable as one tree."""
    facade = bootstrap.build_facade()
    template = tmp_path / "tpl"
    template.mkdir()
    (template / "template.yaml").write_text(
        (FIXTURE / "template.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    created = facade.create_project(tmp_path / "proj", "demo", str(template))

    assert created.ok, [d.model_dump() for d in created.diagnostics]
    pinned = (tmp_path / "proj" / "project.yaml").read_text(encoding="utf-8")
    assert "../tpl" in pinned, pinned


def test_a_template_with_no_relative_path_is_pinned_absolutely(
    tmp_path: Path, arcavex_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two Windows drives have no path between them, and the engine must not call that internal.

    Simulated rather than staged, because a second drive letter cannot be arranged in a test: the
    condition is exactly "relpath cannot express it", which is what this raises.
    """
    real_relpath = os.path.relpath

    def refuse_across_drives(path: object, start: object = None) -> str:
        if Path(str(path)) == (tmp_path / "tpl").resolve():
            raise ValueError("path is on mount 'D:', start on mount 'C:'")
        return real_relpath(path, start)  # type: ignore[arg-type]

    monkeypatch.setattr(projects_module.os.path, "relpath", refuse_across_drives)
    facade = bootstrap.build_facade()
    template = tmp_path / "tpl"
    template.mkdir()
    (template / "template.yaml").write_text(
        (FIXTURE / "template.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    created = facade.create_project(tmp_path / "proj", "demo", str(template))

    assert created.ok, [d.model_dump() for d in created.diagnostics]
    pinned = (tmp_path / "proj" / "project.yaml").read_text(encoding="utf-8")
    assert template.resolve().as_posix() in pinned, pinned


def test_an_absolutely_pinned_template_still_resolves(
    tmp_path: Path, arcavex_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pin is only useful if the project reads it back and renders."""
    monkeypatch.setattr(
        projects_module.os.path,
        "relpath",
        lambda *_: (_ for _ in ()).throw(ValueError("path is on mount 'D:', start on mount 'C:'")),
    )
    facade = bootstrap.build_facade()
    created = facade.create_project(tmp_path / "proj", "demo", str(FIXTURE))
    assert created.ok, [d.model_dump() for d in created.diagnostics]

    report = facade.preview_project(project=tmp_path / "proj", formats=["square"])

    assert report.ok, [d.model_dump() for d in report.diagnostics]
    assert report.previews and report.previews[0].output_path
    # The desktop reads a project through these two, and an absolute pin is only reachable at all
    # since the fix above, so nothing downstream had ever seen one.
    snapshot = facade.project_snapshot(project=tmp_path / "proj")
    assert snapshot.ok, [d.model_dump() for d in snapshot.diagnostics]
    assert snapshot.project_revision
    tree = facade.layer_tree(tmp_path / "proj", mode="authored")
    assert tree.ok and tree.root is not None, [d.model_dump() for d in tree.diagnostics]

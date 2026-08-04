"""Project service tests: create, discovery, status, clone, and the override layer (§5.2/§5.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.library import Library
from arcavex.services.projects import ProjectService, template_stem

REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO = REPO_ROOT / "tests" / "fixtures" / "basic-poster"


def _service(tmp_path: Path) -> ProjectService:
    lib = Library(tmp_path / "templates")
    lib.publish(HELLO, "poster", "1.0.0")
    return ProjectService(lib)


def test_create_pins_library_version_and_scaffolds(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    project = svc.create(tmp_path / "proj", "demo", "poster@1.0.0")
    assert project.manifest.template == "poster@1.0.0"
    assert set(project.manifest.formats) == {"square", "story"}
    assert (project.root / "project.yaml").is_file()
    assert project.data_path is not None and project.data_path.is_file()
    for sub in ("data", "assets", "overrides", "outputs"):
        assert (project.root / sub).is_dir()


def test_create_refuses_non_empty_target(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    target = tmp_path / "proj"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DiagnosticError) as exc:
        svc.create(target, "demo", "poster@1.0.0")
    assert exc.value.diagnostics[0].code == "ARC-PRJ-003"


def test_discovery_walks_up_from_cwd(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    project = svc.create(tmp_path / "proj", "demo", "poster@1.0.0")
    nested = project.root / "data" / "deep"
    nested.mkdir(parents=True)
    found = svc.resolve(start=nested)
    assert found.root == project.root


def test_discovery_none_found(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(DiagnosticError) as exc:
        svc.resolve(start=tmp_path)
    assert exc.value.diagnostics[0].code == "ARC-PRJ-001"


def test_project_override_path_resolves_directory(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    project = svc.create(tmp_path / "proj", "demo", "poster@1.0.0")
    found = svc.resolve(override=project.root)
    assert found.manifest.name == "demo"


def test_set_status_persists(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    project = svc.create(tmp_path / "proj", "demo", "poster@1.0.0")
    svc.set_status(project, "approved")
    assert svc.load(project.root).manifest.status == "approved"
    with pytest.raises(DiagnosticError) as exc:
        svc.set_status(project, "bogus")
    assert exc.value.diagnostics[0].code == "ARC-PRJ-004"


def test_clone_resets_status_and_drops_outputs(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    project = svc.create(tmp_path / "proj", "demo", "poster@1.0.0")
    svc.set_status(project, "approved")
    (project.outputs_dir / "old-run").mkdir(parents=True)
    project = svc.load(project.root)
    clone = svc.clone(project, tmp_path / "clone", "demo2")
    assert clone.manifest.name == "demo2" and clone.manifest.status == "draft"
    assert not any((clone.outputs_dir).iterdir())
    assert (clone.root / "data").is_dir()


def test_project_patch_layer_loaded(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    project = svc.create(tmp_path / "proj", "demo", "poster@1.0.0")
    patch = project.overrides_dir / "poster.patch.yaml"
    patch.write_text(
        "- set: nodes.background.style.fill\n  value: '#000000'\n", encoding="utf-8"
    )
    ops, patch_file = svc.load_project_patch(project)
    assert patch_file == patch and ops is not None and len(ops) == 1


def test_template_stem() -> None:
    assert template_stem("event-poster@1.2.0") == "event-poster"
    assert template_stem("../templates/my-thing") == "my-thing"

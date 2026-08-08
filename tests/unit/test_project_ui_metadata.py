"""Project-owned, non-rendering editor metadata contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from arcavex.kernel.api import (
    LayerUIMetadata,
    ProjectUIMetadata,
    ProjectWorkspaceState,
)
from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import ProjectService
from arcavex.services.template.loader import load_yaml


def _project(root: Path) -> Path:
    project = root / "campaign"
    (project / "template").mkdir(parents=True)
    (project / "template/template.yaml").write_text(
        "version: 0.1.0\n", encoding="utf-8"
    )
    (project / "project.yaml").write_text(
        "name: launch\ntemplate: ./template\nformats: [square]\nlocales: []\n",
        encoding="utf-8",
    )
    return project


def test_missing_ui_metadata_reads_as_defaults_without_writing(tmp_path: Path) -> None:
    """Changing an absent-file read into an eager write would dirty every old project."""
    root = _project(tmp_path)
    projects = ProjectService()

    metadata = projects.load_ui_metadata(projects.load(root))

    assert metadata == ProjectUIMetadata()
    assert metadata.version == 1
    assert metadata.layers == {}
    assert metadata.workspace == ProjectWorkspaceState()
    assert not (root / "project.ui.yaml").exists()


def test_ui_metadata_round_trips_cleanly_and_changes_only_project_revision(
    tmp_path: Path,
) -> None:
    """Dropping metadata fields or entering the render hash breaks desktop persistence/caching."""
    root = _project(tmp_path)
    projects = ProjectService()
    snapshots = ProjectSnapshotService(projects)
    before = snapshots.snapshot(project=root)
    metadata = ProjectUIMetadata(
        layers={
            "hero-title": LayerUIMetadata(
                display_name="Hero title", locked=True, color="#1a2B3c"
            ),
            "legal": LayerUIMetadata(display_name="Legal"),
        },
        workspace=ProjectWorkspaceState(
            active_format="square",
            active_locale="en-CA",
            layer_tree_mode="rendered",
            selected_layer_ids=["hero-title", "legal"],
        ),
    )

    projects.save_ui_metadata(projects.load(root), metadata)
    loaded = projects.load_ui_metadata(projects.load(root))
    after = snapshots.snapshot(project=root)

    assert loaded == metadata
    assert before.project_revision != after.project_revision
    assert before.render_revision == after.render_revision
    assert load_yaml(root / "project.ui.yaml") == {
        "version": 1,
        "layers": {
            "hero-title": {
                "display_name": "Hero title",
                "locked": True,
                "color": "#1a2B3c",
            },
            "legal": {"display_name": "Legal"},
        },
        "workspace": {
            "active_format": "square",
            "active_locale": "en-CA",
            "layer_tree_mode": "rendered",
            "selected_layer_ids": ["hero-title", "legal"],
        },
    }
    assert not list(root.glob(".project.ui.yaml.*.tmp"))


@pytest.mark.parametrize("color", ["red", "#12345", "#gg0011", "112233"])
def test_layer_color_must_be_a_six_digit_hex_color(color: str) -> None:
    """Accepting ambiguous colors would make metadata consumers disagree on presentation."""
    with pytest.raises(ValidationError):
        LayerUIMetadata(color=color)


def test_workspace_rejects_app_global_or_unknown_preferences() -> None:
    """Allowing arbitrary keys would leak app-global layout preferences into project state."""
    with pytest.raises(ValidationError):
        ProjectWorkspaceState.model_validate({"theme": "dark"})


def test_ui_metadata_rejects_an_empty_layer_key() -> None:
    """An empty mapping key cannot identify a stable authored layer."""
    with pytest.raises(ValidationError):
        ProjectUIMetadata(layers={"": LayerUIMetadata(display_name="Missing ID")})


def test_malformed_ui_metadata_returns_a_project_diagnostic(tmp_path: Path) -> None:
    """Malformed sidecar YAML must not escape as an unstructured Pydantic exception."""
    root = _project(tmp_path)
    (root / "project.ui.yaml").write_text(
        "version: 1\nlayers:\n  title:\n    color: red\n", encoding="utf-8"
    )

    with pytest.raises(DiagnosticError) as exc:
        ProjectService().load_ui_metadata(ProjectService().load(root))

    assert exc.value.diagnostics[0].code == "ARC-PRJ-008"
    assert exc.value.diagnostics[0].source is not None
    assert exc.value.diagnostics[0].source.file == str(root / "project.ui.yaml")

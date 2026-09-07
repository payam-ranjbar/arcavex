"""Properties of canonical project and render revision manifests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import ProjectService

_AUTHORED_FILES = (
    ("template/template.yaml", b"version: 0.1.0\n"),
    ("template/schema.yaml", b"title: {type: string}\n"),
    ("data/content.yaml", b"title: Launch\n"),
    ("overrides/template.patch.yaml", b"- set: nodes.title.text\n  value: Launch\n"),
    ("assets/hero.bin", bytes((0, 13, 10, 255))),
    ("project.ui.yaml", b"version: 1\nlayers: {}\n"),
)

_PROJECT_YAML = b"""name: launch
template: ./template
style: midnight@1.0.0
formats: [story, square]
locales: [fa, en]
data: data/content.yaml
dpi: 144
status: draft
tags: [summer]
automation: {mode: unrestricted}
"""


def _write_project(
    root: Path,
    authored: tuple[tuple[str, bytes], ...] = _AUTHORED_FILES,
    *,
    project_yaml: bytes = _PROJECT_YAML,
) -> None:
    root.mkdir(parents=True)
    (root / "project.yaml").write_bytes(project_yaml)
    for relative, content in authored:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _snapshot(root: Path):
    return ProjectSnapshotService(ProjectService()).snapshot(project=root)


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(order=st.permutations(_AUTHORED_FILES))
def test_revisions_ignore_filesystem_creation_and_traversal_order(
    tmp_path: Path, order: list[tuple[str, bytes]]
) -> None:
    """A different directory enumeration order must not alter either revision."""
    with TemporaryDirectory(dir=tmp_path) as generated:
        canonical = Path(generated) / "canonical"
        permuted = Path(generated) / "permuted"
        _write_project(canonical)
        _write_project(permuted, tuple(order))

        first = _snapshot(canonical)
        second = _snapshot(permuted)

        assert first.ok and second.ok
        assert first.project_manifest == second.project_manifest
        assert first.render_manifest == second.render_manifest
        assert first.project_revision == second.project_revision
        assert first.render_revision == second.render_revision


@pytest.mark.parametrize("line_ending", [b"\r\n", b"\r"])
def test_utf8_line_endings_normalize_to_lf(tmp_path: Path, line_ending: bytes) -> None:
    """Equivalent UTF-8 text checkouts must have identical cross-platform revisions."""
    lf_root = tmp_path / "lf"
    variant_root = tmp_path / "variant"
    _write_project(lf_root)
    variant_files = tuple(
        (path, content.replace(b"\n", line_ending) if path != "assets/hero.bin" else content)
        for path, content in _AUTHORED_FILES
    )
    _write_project(
        variant_root,
        variant_files,
        project_yaml=_PROJECT_YAML.replace(b"\n", line_ending),
    )

    lf = _snapshot(lf_root)
    variant = _snapshot(variant_root)

    assert lf.project_manifest == variant.project_manifest
    assert lf.render_manifest == variant.render_manifest
    assert lf.project_revision == variant.project_revision
    assert lf.render_revision == variant.render_revision


def test_ui_status_tags_and_automation_change_only_project_revision(tmp_path: Path) -> None:
    """Editor metadata and workflow policy must never invalidate a render cache key."""
    root = tmp_path / "campaign"
    _write_project(root)
    initial = _snapshot(root)

    (root / "project.ui.yaml").write_text(
        "version: 1\nlayers: {title: {locked: true}}\n", encoding="utf-8"
    )
    ui_changed = _snapshot(root)
    (root / "project.yaml").write_bytes(
        _PROJECT_YAML.replace(b"status: draft", b"status: approved")
        .replace(b"tags: [summer]", b"tags: [launch, urgent]")
        .replace(b"mode: unrestricted", b"mode: review")
    )
    policy_changed = _snapshot(root)

    assert initial.project_revision != ui_changed.project_revision
    assert ui_changed.project_revision != policy_changed.project_revision
    assert initial.render_revision == ui_changed.render_revision == policy_changed.render_revision


@pytest.mark.parametrize(
    ("relative", "replacement"),
    [
        ("template/schema.yaml", b"title: {type: number}\n"),
        ("data/content.yaml", b"title: Revised\n"),
        ("overrides/template.patch.yaml", b"- remove: nodes.title\n"),
        ("assets/hero.bin", bytes((0, 13, 10, 254))),
    ],
)
def test_render_input_content_changes_both_revisions(
    tmp_path: Path, relative: str, replacement: bytes
) -> None:
    """Every project-owned render input must invalidate both revisions."""
    root = tmp_path / "campaign"
    _write_project(root)
    before = _snapshot(root)

    (root / relative).write_bytes(replacement)
    after = _snapshot(root)

    assert before.project_revision != after.project_revision
    assert before.render_revision != after.render_revision


def test_pinned_references_and_render_projection_fields_change_render_revision(
    tmp_path: Path,
) -> None:
    """Changing a template pin, style, target axes, data ref, or DPI must invalidate render."""
    root = tmp_path / "campaign"
    _write_project(root)
    (root / "template-v2").mkdir()
    (root / "template-v2/template.yaml").write_bytes(b"version: 0.1.0\n")
    before = _snapshot(root)
    changed_yaml = (
        _PROJECT_YAML.replace(b"./template", b"./template-v2")
        .replace(b"midnight@1.0.0", b"midnight@2.0.0")
        .replace(b"[story, square]", b"[square]")
        .replace(b"[fa, en]", b"[en]")
        .replace(b"data/content.yaml", b"data/revised.yaml")
        .replace(b"dpi: 144", b"dpi: 300")
    )
    (root / "data/revised.yaml").write_bytes(b"title: Launch\n")
    (root / "project.yaml").write_bytes(changed_yaml)

    after = _snapshot(root)

    assert before.project_revision != after.project_revision
    assert before.render_revision != after.render_revision


def test_binary_asset_line_endings_are_not_normalized(tmp_path: Path) -> None:
    """Binary asset bytes must remain byte-sensitive even when they resemble text newlines."""
    root = tmp_path / "campaign"
    _write_project(root)
    before = _snapshot(root)

    (root / "assets/hero.bin").write_bytes(bytes((0, 10, 255)))
    after = _snapshot(root)

    assert before.project_revision != after.project_revision
    assert before.render_revision != after.render_revision


def test_outputs_caches_temporary_files_and_working_queues_change_neither_revision(
    tmp_path: Path,
) -> None:
    """Runtime artifacts must not create false conflicts or preview invalidations."""
    root = tmp_path / "campaign"
    _write_project(root)
    before = _snapshot(root)
    ignored = {
        "template/outputs/render.png": b"output",
        "template/cache/preview.png": b"cache",
        "template/.cache/index": b"cache",
        "template/source.yaml.tmp": b"temporary",
        "template/.arcavex/pending/command.json": b"proposal",
        "template/.arcavex/history/record.json": b"working queue",
    }
    for relative, content in ignored.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    after = _snapshot(root)

    assert before.project_manifest == after.project_manifest
    assert before.render_manifest == after.render_manifest
    assert before.project_revision == after.project_revision
    assert before.render_revision == after.render_revision

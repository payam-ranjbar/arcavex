"""Backward-compatible project automation and extension policy."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

import pytest

from arcavex.kernel.api import (
    AutomationPolicy,
    LayerUIMetadata,
    ProjectPolicyReport,
    ProjectUIMetadata,
)
from arcavex.services.fsutil import file_lock
from arcavex.services.project_policy import ProjectPolicyService
from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import ProjectService
from arcavex.services.template.loader import load_yaml


def _comment_values(value: Any) -> list[str]:
    """Collect ruamel's parsed comment tokens without asserting against source text."""
    found: list[str] = []

    def collect_tokens(tokens: Any) -> None:
        if tokens is None:
            return
        token_value = getattr(tokens, "value", None)
        if isinstance(token_value, str):
            found.append(token_value)
            return
        if isinstance(tokens, dict):
            for item in tokens.values():
                collect_tokens(item)
        elif isinstance(tokens, (list, tuple)):
            for item in tokens:
                collect_tokens(item)

    comments = getattr(value, "ca", None)
    if comments is not None:
        collect_tokens(comments.comment)
        collect_tokens(comments.items)
        collect_tokens(comments.end)
    if isinstance(value, dict):
        for item in value.values():
            found.extend(_comment_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_comment_values(item))
    return found


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


def test_old_manifest_loads_with_unrestricted_defaults_without_rewrite(
    tmp_path: Path,
) -> None:
    """Making automation required would break every existing project manifest."""
    root = _project(tmp_path)
    before = (root / "project.yaml").read_bytes()

    project = ProjectService().load(root)

    assert project.manifest.automation == AutomationPolicy()
    assert project.manifest.automation.mode == "unrestricted"
    assert project.manifest.automation.extensions == "unrestricted"
    assert (root / "project.yaml").read_bytes() == before


def test_manifest_persists_only_nondefault_policy_using_versioned_mapping(
    tmp_path: Path,
) -> None:
    """Dropping one policy axis or serializing default noise would violate manifest conventions."""
    root = _project(tmp_path)
    projects = ProjectService()
    loaded = projects.load(root)
    updated = loaded.manifest.model_copy(
        update={
            "automation": AutomationPolicy(mode="review", extensions="disabled")
        }
    )

    projects.save(loaded.__class__(root=loaded.root, manifest=updated))

    raw = load_yaml(root / "project.yaml")
    assert raw["automation"] == {
        "version": 1,
        "mode": "review",
        "extensions": "disabled",
    }
    assert projects.load(root).manifest.automation == AutomationPolicy(
        mode="review", extensions="disabled"
    )
    assert not list(root.glob(".project.yaml.*.tmp"))


def test_default_policy_is_omitted_when_manifest_is_saved(tmp_path: Path) -> None:
    """Returning to approved defaults should restore the clean old-manifest shape."""
    root = _project(tmp_path)
    path = root / "project.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "automation:\n  version: 1\n  mode: review\n  extensions: disabled\n",
        encoding="utf-8",
    )
    projects = ProjectService()
    project = projects.load(root)
    defaulted = project.manifest.model_copy(update={"automation": AutomationPolicy()})

    projects.save(project.__class__(root=project.root, manifest=defaulted))

    assert "automation" not in load_yaml(path)


def test_nondefault_policy_omits_the_other_unrestricted_axis(tmp_path: Path) -> None:
    """A changed mode must not add unrelated default extension policy noise."""
    root = _project(tmp_path)
    projects = ProjectService()
    project = projects.load(root)
    changed = project.manifest.model_copy(
        update={"automation": AutomationPolicy(mode="review")}
    )

    projects.save(project.__class__(root=project.root, manifest=changed))

    assert load_yaml(root / "project.yaml")["automation"] == {
        "version": 1,
        "mode": "review",
    }


def test_policy_update_preserves_unknown_nested_manifest_fields_and_comments(
    tmp_path: Path,
) -> None:
    """Reconstructing ProjectModel would erase future/vendor manifest data and comments."""
    root = _project(tmp_path)
    path = root / "project.yaml"
    path.write_text(
        """\
# project header retained for authors
name: launch
template: ./template
formats: [square]
locales: []
vendor:
  # nested integration note
  integration:
    enabled: true
    options:
      quality: archival  # inline option note
future_feature:
  stages: [draft, final]
automation:
  version: 1
  mode: unrestricted
""",
        encoding="utf-8",
    )
    before = load_yaml(path)
    before_comments = _comment_values(before)
    projects = ProjectService()
    policies = ProjectPolicyService(projects, ProjectSnapshotService(projects))

    report = policies.set_policy(
        project=root, mode="read_only", extensions="disabled"
    )
    after = load_yaml(path)

    assert report.ok
    assert after["vendor"] == {
        "integration": {
            "enabled": True,
            "options": {"quality": "archival"},
        }
    }
    assert after["future_feature"] == {"stages": ["draft", "final"]}
    assert after["automation"] == {
        "version": 1,
        "mode": "read_only",
        "extensions": "disabled",
    }
    assert _comment_values(after) == before_comments


def test_policy_service_reports_revisions_and_changes_only_project_revision(
    tmp_path: Path,
) -> None:
    """Policy changes must invalidate semantic mutations without invalidating render caches."""
    root = _project(tmp_path)
    projects = ProjectService()
    snapshots = ProjectSnapshotService(projects)
    policies = ProjectPolicyService(projects, snapshots)
    before = snapshots.snapshot(project=root)

    report = policies.set_policy(
        project=root, mode="read_only", extensions="disabled"
    )
    after = snapshots.snapshot(project=root)

    assert isinstance(report, ProjectPolicyReport)
    assert report.ok
    assert report.canonical_path == str(root.resolve())
    assert report.policy == AutomationPolicy(
        mode="read_only", extensions="disabled"
    )
    assert report.project_revision == after.project_revision
    assert report.render_revision == after.render_revision
    assert before.project_revision != after.project_revision
    assert before.render_revision == after.render_revision
    assert policies.get_policy(project=root).policy == report.policy


def test_policy_and_ui_writes_share_the_project_mutation_lock(tmp_path: Path) -> None:
    """Separate locks would let two project-revision writers publish concurrently."""
    root = _project(tmp_path)
    projects = ProjectService()
    snapshots = ProjectSnapshotService(projects)
    policies = ProjectPolicyService(projects, snapshots)
    metadata = ProjectUIMetadata(
        layers={"title": LayerUIMetadata(display_name="Hero")}
    )
    lock_path = root / ".arcavex/project.lock"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with file_lock(lock_path):
            policy_future = pool.submit(
                policies.set_policy,
                project=root,
                mode="review",
                extensions="disabled",
            )
            ui_future = pool.submit(
                projects.save_ui_metadata, projects.load(root), metadata
            )
            with pytest.raises(FutureTimeoutError):
                policy_future.result(timeout=0.2)
            with pytest.raises(FutureTimeoutError):
                ui_future.result(timeout=0.2)

        policy = policy_future.result(timeout=2)
        saved_metadata = ui_future.result(timeout=2)

    assert policy.ok and policy.policy.mode == "review"
    assert saved_metadata == metadata
    assert projects.load_ui_metadata(projects.load(root)) == metadata

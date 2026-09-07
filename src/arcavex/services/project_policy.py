"""Project-local automation and extension policy operations."""

from __future__ import annotations

from pathlib import Path

from arcavex.kernel.api import (
    AutomationMode,
    AutomationPolicy,
    ExtensionMode,
    ProjectPolicyReport,
)
from arcavex.services.project_locking import project_mutation_lock
from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import Project, ProjectService


class ProjectPolicyService:
    """Read and atomically update the optional policy mapping in ``project.yaml``."""

    def __init__(
        self, projects: ProjectService, snapshots: ProjectSnapshotService
    ) -> None:
        self._projects = projects
        self._snapshots = snapshots

    def get_policy(
        self, *, start: Path | None = None, project: Path | None = None
    ) -> ProjectPolicyReport:
        """Return the effective policy and current revisions without writing defaults."""
        loaded = self._projects.resolve(start, project)
        return self._report(loaded)

    def set_policy(
        self,
        *,
        mode: AutomationMode,
        extensions: ExtensionMode,
        start: Path | None = None,
        project: Path | None = None,
    ) -> ProjectPolicyReport:
        """Persist a validated policy atomically and return its fresh revisions."""
        loaded = self._projects.resolve(start, project)
        policy = AutomationPolicy(mode=mode, extensions=extensions)
        with project_mutation_lock(loaded.root):
            loaded = self._projects.load(loaded.root)
            updated = self._projects.save_automation_policy(loaded, policy)
            return self._report(updated)

    def _report(self, project: Project) -> ProjectPolicyReport:
        snapshot = self._snapshots.snapshot(project=project.root)
        return ProjectPolicyReport(
            ok=snapshot.ok,
            canonical_path=snapshot.canonical_path,
            policy=project.manifest.automation,
            project_revision=snapshot.project_revision,
            render_revision=snapshot.render_revision,
            diagnostics=list(snapshot.diagnostics),
        )

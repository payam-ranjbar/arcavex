"""Read-only project snapshots with independent semantic and render revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal

from arcavex.kernel.api import (
    ProjectSnapshotReport,
    ProjectSourceFile,
    ProjectTarget,
    RevisionManifestEntry,
)
from arcavex.kernel.diagnostics import Diagnostic, diagnostic, has_errors
from arcavex.services.projects import Project, ProjectService

SourceRole = Literal["project", "ui", "template", "data", "override", "asset"]

_RENDER_PROJECTION_PATH = "@project/render-inputs.json"
_EXCLUDED_DIRECTORIES = frozenset(
    {".arcavex", ".cache", "__pycache__", "cache", "caches", "outputs"}
)
_TEMPORARY_SUFFIXES = (".swp", ".tmp", "~")


class ProjectSnapshotService:
    """Resolve and hash a project without creating, updating, or caching anything."""

    def __init__(self, projects: ProjectService) -> None:
        self._projects = projects

    def snapshot(
        self,
        *,
        start: Path | None = None,
        project: Path | None = None,
        capabilities: Sequence[str] = (),
    ) -> ProjectSnapshotReport:
        """Return the current project and render revisions from normalized source manifests."""
        loaded = self._projects.resolve(start, project)
        root = loaded.root.resolve()
        template_path, template_ref, is_library = self._projects.resolve_template(loaded)
        template_path = template_path.resolve()
        owned: dict[str, tuple[Path, SourceRole]] = {}
        missing: list[tuple[str, Path, SourceRole]] = []

        self._add_required(owned, missing, root, root / "project.yaml", "project")
        self._add_optional(owned, root, root / "project.ui.yaml", "ui")
        if loaded.data_path is not None:
            self._add_required(owned, missing, root, loaded.data_path.resolve(), "data")
        self._add_tree(owned, root, root / "overrides", "override")
        self._add_tree(owned, root, root / "assets", "asset")

        template_is_owned = _is_within(template_path, root)
        if template_is_owned:
            if template_path.is_file():
                self._add_required(owned, missing, root, template_path, "template")
            elif template_path.is_dir():
                self._add_required(
                    owned, missing, root, template_path / "template.yaml", "template"
                )
                self._add_tree(owned, root, template_path, "template")
            else:
                self._add_required(owned, missing, root, template_path, "template")

        entries = {
            relative: _manifest_entry(relative, path, role)
            for relative, (path, role) in owned.items()
        }
        project_manifest = [entries[path] for path in sorted(entries)]
        render_paths = sorted(
            path
            for path, (_, role) in owned.items()
            if role in {"template", "data", "override", "asset"}
        )
        projection = _render_projection(loaded, template_ref)
        render_manifest = [
            _entry_from_bytes(_RENDER_PROJECTION_PATH, projection),
            *(entries[path] for path in render_paths),
        ]
        source_files = [
            _source_file(relative, path, role, entries[relative].sha256)
            for relative, (path, role) in owned.items()
        ]
        source_files.extend(
            _source_file(relative, path, role, None)
            for relative, path, role in missing
        )
        if is_library or not template_is_owned:
            source_files.append(
                ProjectSourceFile(
                    path=template_ref,
                    resolved_path=str(template_path),
                    role="template",
                    project_owned=False,
                )
            )
        source_files.sort(key=lambda source: (source.path, source.resolved_path))

        diagnostics = [_missing_diagnostic(path, role) for _, path, role in missing]
        targets = [
            ProjectTarget(format=format_name, locale=locale)
            for format_name, locale in self._projects.render_targets(loaded)
        ]
        manifest = loaded.manifest
        return ProjectSnapshotReport(
            ok=not has_errors(diagnostics),
            canonical_path=str(root),
            name=manifest.name,
            template=template_ref,
            style=manifest.style,
            data=manifest.data,
            dpi=manifest.dpi,
            formats=list(manifest.formats),
            locales=list(manifest.locales),
            targets=targets,
            default_target=targets[0] if targets else None,
            status=manifest.status,
            tags=list(manifest.tags),
            project_revision=_revision(project_manifest),
            render_revision=_revision(render_manifest),
            project_manifest=project_manifest,
            render_manifest=render_manifest,
            source_files=source_files,
            capabilities=sorted(set(capabilities)),
            diagnostics=diagnostics,
        )

    def _add_required(
        self,
        owned: dict[str, tuple[Path, SourceRole]],
        missing: list[tuple[str, Path, SourceRole]],
        root: Path,
        path: Path,
        role: SourceRole,
    ) -> None:
        if path.is_file():
            self._add_file(owned, root, path, role)
            return
        missing.append((_relative_or_posix(path, root), path, role))

    def _add_optional(
        self,
        owned: dict[str, tuple[Path, SourceRole]],
        root: Path,
        path: Path,
        role: SourceRole,
    ) -> None:
        if path.is_file():
            self._add_file(owned, root, path, role)

    def _add_tree(
        self,
        owned: dict[str, tuple[Path, SourceRole]],
        root: Path,
        directory: Path,
        role: SourceRole,
    ) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file() and not _is_excluded(path, root):
                self._add_file(owned, root, path, role)

    def _add_file(
        self,
        owned: dict[str, tuple[Path, SourceRole]],
        root: Path,
        path: Path,
        role: SourceRole,
    ) -> None:
        if _is_excluded(path, root):
            return
        relative = path.resolve().relative_to(root).as_posix()
        owned.setdefault(relative, (path.resolve(), role))


def _manifest_entry(relative: str, path: Path, role: SourceRole) -> RevisionManifestEntry:
    normalized = _normalized_bytes(path, role)
    return _entry_from_bytes(relative, normalized)


def _entry_from_bytes(path: str, content: bytes) -> RevisionManifestEntry:
    return RevisionManifestEntry(
        path=path,
        sha256=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
    )


def _normalized_bytes(path: Path, role: SourceRole) -> bytes:
    raw = path.read_bytes()
    if role == "asset":
        return raw
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _render_projection(project: Project, template_ref: str) -> bytes:
    manifest = project.manifest
    payload = {
        "data": manifest.data,
        "dpi": manifest.dpi,
        "formats": list(manifest.formats),
        "locales": list(manifest.locales),
        "style": manifest.style,
        "template": template_ref,
    }
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _revision(entries: Iterable[RevisionManifestEntry]) -> str:
    payload = [entry.model_dump(mode="json") for entry in entries]
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _source_file(
    relative: str,
    path: Path,
    role: SourceRole,
    sha256: str | None,
) -> ProjectSourceFile:
    return ProjectSourceFile(
        path=relative,
        resolved_path=str(path.resolve()),
        role=role,
        project_owned=True,
        sha256=sha256,
    )


def _missing_diagnostic(path: Path, role: SourceRole) -> Diagnostic:
    return diagnostic(
        "ARC-PRJ-005",
        f"Declared project {role} source does not exist: {path}",
        file=str(path.resolve()),
        hint="Restore the declared file or update project.yaml to reference an existing source.",
    )


def _relative_or_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.resolve().relative_to(root).parts
    except ValueError:
        return False
    if any(part.casefold() in _EXCLUDED_DIRECTORIES for part in parts[:-1]):
        return True
    name = parts[-1].casefold()
    return (
        name.startswith(".tmp-")
        or name.startswith("~$")
        or name.endswith(_TEMPORARY_SUFFIXES)
    )

"""Read-only project snapshots with independent semantic and render revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _Source:
    path: Path
    role: SourceRole
    project_owned: bool
    render_relevant: bool


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
        sources: dict[str, _Source] = {}
        missing: dict[str, _Source] = {}

        self._add_required(
            sources, missing, root, root / "project.yaml", "project", "project.yaml"
        )
        self._add_optional(
            sources, root, root / "project.ui.yaml", "ui", "project.ui.yaml"
        )
        if loaded.data_path is not None:
            data_path = loaded.data_path.resolve()
            self._add_required(
                sources,
                missing,
                root,
                data_path,
                "data",
                _logical_path(data_path, root, "@external/data"),
                render_relevant=True,
            )
        self._add_tree(
            sources,
            root,
            root / "overrides",
            "override",
            render_path=loaded.patch_path.resolve(),
        )
        self._add_tree(sources, root, root / "assets", "asset", render_all=True)

        if not is_library:
            if template_path.is_file():
                self._add_required(
                    sources,
                    missing,
                    root,
                    template_path,
                    "template",
                    _template_logical_path(template_path, template_path.parent, root),
                    render_relevant=True,
                )
            elif template_path.is_dir():
                self._add_required(
                    sources,
                    missing,
                    root,
                    template_path / "template.yaml",
                    "template",
                    _template_logical_path(
                        template_path / "template.yaml", template_path, root
                    ),
                    render_relevant=True,
                )
                self._add_tree(
                    sources,
                    root,
                    template_path,
                    "template",
                    logical_root=template_path,
                    render_all=True,
                )
            else:
                self._add_required(
                    sources,
                    missing,
                    root,
                    template_path,
                    "template",
                    _logical_path(template_path, root, "@external/template"),
                    render_relevant=True,
                )

        entries = {
            logical: _manifest_entry(logical, source.path, source.role)
            for logical, source in sources.items()
        }
        project_manifest = [
            entries[logical]
            for logical, source in sorted(sources.items())
            if source.project_owned
        ]
        render_paths = sorted(
            logical for logical, source in sources.items() if source.render_relevant
        )
        projection = _render_projection(
            loaded,
            _canonical_template_ref(template_path, template_ref, is_library, root),
            _canonical_data_ref(loaded, root),
        )
        render_manifest = [
            _entry_from_bytes(_RENDER_PROJECTION_PATH, projection),
            *(entries[path] for path in render_paths),
        ]
        source_files = [
            _source_file(logical, source, entries[logical].sha256)
            for logical, source in sources.items()
        ]
        source_files.extend(
            _source_file(logical, source, None) for logical, source in missing.items()
        )
        if is_library:
            source_files.append(
                ProjectSourceFile(
                    path=template_ref,
                    resolved_path=str(template_path),
                    role="template",
                    project_owned=False,
                )
            )
        source_files.sort(key=lambda source: (source.path, source.resolved_path))

        diagnostics = [
            _missing_diagnostic(source.path, source.role)
            for _, source in sorted(missing.items())
        ]
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
        sources: dict[str, _Source],
        missing: dict[str, _Source],
        root: Path,
        path: Path,
        role: SourceRole,
        logical: str,
        *,
        render_relevant: bool = False,
    ) -> None:
        if path.is_file():
            self._add_file(
                sources,
                root,
                path,
                role,
                logical,
                render_relevant=render_relevant,
            )
            return
        resolved = path.resolve()
        missing.setdefault(
            logical,
            _Source(
                path=resolved,
                role=role,
                project_owned=_is_within(resolved, root),
                render_relevant=render_relevant,
            ),
        )

    def _add_optional(
        self,
        sources: dict[str, _Source],
        root: Path,
        path: Path,
        role: SourceRole,
        logical: str,
    ) -> None:
        if path.is_file():
            self._add_file(sources, root, path, role, logical)

    def _add_tree(
        self,
        sources: dict[str, _Source],
        root: Path,
        directory: Path,
        role: SourceRole,
        *,
        logical_root: Path | None = None,
        render_all: bool = False,
        render_path: Path | None = None,
    ) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file() and not _is_excluded(path, directory):
                resolved = path.resolve()
                logical = (
                    _template_logical_path(path, logical_root, root)
                    if logical_root is not None
                    else resolved.relative_to(root).as_posix()
                )
                self._add_file(
                    sources,
                    root,
                    resolved,
                    role,
                    logical,
                    render_relevant=(
                        render_all
                        or (render_path is not None and resolved == render_path)
                    ),
                )

    def _add_file(
        self,
        sources: dict[str, _Source],
        root: Path,
        path: Path,
        role: SourceRole,
        logical: str,
        *,
        render_relevant: bool = False,
    ) -> None:
        if _is_excluded(path, root):
            return
        resolved = path.resolve()
        sources.setdefault(
            logical,
            _Source(
                path=resolved,
                role=role,
                project_owned=_is_within(resolved, root),
                render_relevant=render_relevant,
            ),
        )


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
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    if role == "asset" and _has_binary_controls(text):
        return raw
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _has_binary_controls(text: str) -> bool:
    allowed = {"\t", "\n", "\r"}
    return any(
        (ord(character) < 32 and character not in allowed)
        or 127 <= ord(character) <= 159
        for character in text
    )


def _render_projection(
    project: Project, template_ref: str, data_ref: str | None
) -> bytes:
    manifest = project.manifest
    payload = {
        "data": data_ref,
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
    logical: str,
    source: _Source,
    sha256: str | None,
) -> ProjectSourceFile:
    return ProjectSourceFile(
        path=logical,
        resolved_path=str(source.path),
        role=source.role,
        project_owned=source.project_owned,
        sha256=sha256,
    )


def _missing_diagnostic(path: Path, role: SourceRole) -> Diagnostic:
    return diagnostic(
        "ARC-PRJ-005",
        f"Declared project {role} source does not exist: {path}",
        file=str(path.resolve()),
        hint="Restore the declared file or update project.yaml to reference an existing source.",
    )


def _logical_path(path: Path, root: Path, external: str) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return external


def _template_logical_path(path: Path, template_root: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return f"@external/template/{path.relative_to(template_root).as_posix()}"


def _canonical_template_ref(
    path: Path, reference: str, is_library: bool, root: Path
) -> str:
    if is_library:
        return reference
    return _logical_path(path, root, "@external/template")


def _canonical_data_ref(project: Project, root: Path) -> str | None:
    if project.data_path is None:
        return None
    return _logical_path(project.data_path, root, "@external/data")


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

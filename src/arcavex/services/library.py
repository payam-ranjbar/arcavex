"""Versioned local template library (spec §5.1, §5.5).

Library templates live immutably under ``$ARCAVEX_HOME/templates/<name>/<version>/`` beside an
``index.toml`` listing the available versions and an optional default alias. Publishing writes a
new version directory and never edits an existing one — immutability begins at publish, so a
project that pinned ``name@1.0.0`` keeps rendering the exact bytes it always did. Bare-name
references resolve only through an explicit default alias; Arcavex never silently selects
"latest" for a recorded render (§5.1). Publication and index updates take a cross-process lock
so two publishers cannot race the same version directory or clobber the index.
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.fsutil import atomic_write_text, file_lock, home_dir


@dataclass(frozen=True)
class ResolvedTemplate:
    """A resolved library template: its name, exact version, and on-disk directory."""

    name: str
    version: str
    path: Path


@dataclass(frozen=True)
class TemplateIndex:
    """A template's available versions and optional default alias (from ``index.toml``)."""

    name: str
    versions: list[str] = field(default_factory=list)
    default: str | None = None


def is_library_ref(ref: str) -> bool:
    """Whether ``ref`` is a library ``name`` / ``name@version`` reference, not a filesystem path.

    A path (contains a separator, starts with ``.``/``~``, or names an existing file/dir) is not
    a library reference; a bare identifier or ``name@version`` is.
    """
    if ref.endswith((".yaml", ".yml")):
        return False
    if ref.startswith((".", "/", "~")) or "/" in ref or "\\" in ref:
        return False
    if Path(ref).exists():
        return False
    return True


class Library:
    """Reads and publishes versioned templates under the global library root."""

    def __init__(self, root: Path | None = None) -> None:
        """Bind to ``root`` (defaults to ``$ARCAVEX_HOME/templates``)."""
        self._root = Path(root) if root is not None else home_dir() / "templates"

    @property
    def root(self) -> Path:
        """The ``templates/`` root directory."""
        return self._root

    def resolve(self, ref: str) -> ResolvedTemplate:
        """Resolve a ``name`` or ``name@version`` reference to an exact version directory.

        A bare ``name`` resolves through the index's explicit default alias; without one it is a
        located ``ARC-LIB-003`` (never a silent "latest"). ``name@version`` requires that exact
        version to exist (``ARC-LIB-001`` otherwise).
        """
        name, _, version = ref.partition("@")
        index = self.index(name)
        if not index.versions:
            raise DiagnosticError(
                diagnostic(
                    "ARC-LIB-001",
                    f"Unknown library template {name!r}",
                    hint=f"Published templates: {self._available_names() or '(none)'}.",
                )
            )
        if version:
            if version not in index.versions:
                available = ", ".join(index.versions)
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LIB-001",
                        f"Template {name!r} has no version {version!r}",
                        hint=f"Available versions: {available}.",
                    )
                )
            resolved = version
        else:
            if index.default is None:
                available = ", ".join(index.versions)
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LIB-003",
                        f"Template {name!r} has no default version; a bare name is ambiguous",
                        hint=(
                            f"Reference an explicit '{name}@<version>' "
                            f"(available: {available}), or set a default alias."
                        ),
                    )
                )
            resolved = index.default
        return ResolvedTemplate(name=name, version=resolved, path=self.version_dir(name, resolved))

    def index(self, name: str) -> TemplateIndex:
        """Return the version index for ``name`` (empty when the template is not published)."""
        index_path = self._name_dir(name) / "index.toml"
        if not index_path.is_file():
            return TemplateIndex(name=name)
        try:
            data = tomllib.loads(index_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-LIB-004",
                    f"Library index for {name!r} is not valid TOML",
                    file=str(index_path),
                    hint="Delete the index to let a republish regenerate it (indexes are "
                    "disposable; version directories are canonical).",
                )
            ) from exc
        versions = [str(v) for v in data.get("versions", [])]
        default = data.get("default")
        return TemplateIndex(
            name=name,
            versions=sorted(versions, key=_version_key),
            default=str(default) if default is not None else None,
        )

    def list_templates(self) -> list[TemplateIndex]:
        """Return every published template's index, sorted by name."""
        if not self._root.is_dir():
            return []
        names = sorted(p.name for p in self._root.iterdir() if p.is_dir())
        return [self.index(name) for name in names]

    def version_dir(self, name: str, version: str) -> Path:
        """Return the (immutable) directory for ``name@version``."""
        return self._name_dir(name) / version

    def publish(
        self, template_dir: Path, name: str, version: str, *, set_default: bool = True
    ) -> ResolvedTemplate:
        """Copy ``template_dir`` into an immutable ``name/version/`` directory and index it.

        Refuses to overwrite an existing version (``ARC-LIB-002``) — a change is a new version,
        never an in-place edit (§5.5). Under a cross-process lock the version directory is
        materialized via a temporary sibling then atomically renamed, and the index is rewritten
        to include the new version (and, unless ``set_default`` is false, to point the default
        alias at it).
        """
        template_dir = Path(template_dir)
        if not (template_dir / "template.yaml").is_file():
            raise DiagnosticError(
                diagnostic(
                    "ARC-LIB-001",
                    f"Not a template directory (no template.yaml): {template_dir}",
                    file=str(template_dir),
                    hint="Publish a directory containing a 'template.yaml'.",
                )
            )
        if not _valid_version(version):
            raise DiagnosticError(
                diagnostic(
                    "ARC-LIB-004",
                    f"Invalid version string {version!r}",
                    hint="Use a dotted version such as '1.0.0' (optionally with a '-pre' suffix).",
                )
            )
        name_dir = self._name_dir(name)
        target = name_dir / version
        with file_lock(name_dir / ".lock"):
            if target.exists():
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LIB-002",
                        f"Version {version!r} of {name!r} is already published",
                        file=str(target),
                        hint="Published versions are immutable — publish a new version instead.",
                    )
                )
            name_dir.mkdir(parents=True, exist_ok=True)
            staging = name_dir / f".staging-{version}"
            if staging.exists():
                shutil.rmtree(staging)
            shutil.copytree(template_dir, staging)
            os_replace_dir(staging, target)
            index = self.index(name)
            versions = sorted({*index.versions, version}, key=_version_key)
            default = version if set_default else index.default
            self._write_index(name, versions, default)
        return ResolvedTemplate(name=name, version=version, path=target)

    def set_default(self, name: str, version: str) -> None:
        """Point the default alias for ``name`` at an existing ``version`` (explicit alias)."""
        index = self.index(name)
        if version not in index.versions:
            raise DiagnosticError(
                diagnostic(
                    "ARC-LIB-001",
                    f"Template {name!r} has no version {version!r} to make default",
                    hint=f"Available versions: {', '.join(index.versions) or '(none)'}.",
                )
            )
        with file_lock(self._name_dir(name) / ".lock"):
            self._write_index(name, index.versions, version)

    # -------------------------------------------------------------------- internals
    def _name_dir(self, name: str) -> Path:
        return self._root / name

    def _write_index(self, name: str, versions: list[str], default: str | None) -> None:
        lines: list[str] = []
        if default is not None:
            lines.append(f'default = "{default}"')
        rendered = ", ".join(f'"{v}"' for v in versions)
        lines.append(f"versions = [{rendered}]")
        atomic_write_text(self._name_dir(name) / "index.toml", "\n".join(lines) + "\n")

    def _available_names(self) -> str:
        if not self._root.is_dir():
            return ""
        return ", ".join(sorted(p.name for p in self._root.iterdir() if p.is_dir()))


def os_replace_dir(src: Path, dst: Path) -> None:
    """Atomically move directory ``src`` onto ``dst`` (both on the same filesystem)."""
    import os

    os.replace(src, dst)


def _valid_version(version: str) -> bool:
    """Whether ``version`` is a dotted version with an optional pre-release suffix."""
    if not version:
        return False
    main, _, pre = version.partition("-")
    parts = main.split(".")
    if not all(p.isdigit() for p in parts) or not parts:
        return False
    return pre == "" or all(c.isalnum() or c in ".-" for c in pre)


def _version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    """Sort key ordering versions numerically, with pre-releases below their release."""
    main, _, pre = version.partition("-")
    nums = tuple(int(p) if p.isdigit() else 0 for p in main.split("."))
    # A release (no pre-release) sorts above its own pre-releases: rank 1 vs 0.
    return (nums, 0 if pre else 1, pre)

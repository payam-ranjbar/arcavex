"""Projects: the campaign tracking unit (spec §5.2, §6.1.2).

A project is one directory holding a ``project.yaml`` manifest, its data and assets, its
overrides (patch files, never template forks — §5.4), and its recorded ``outputs/`` runs. This
service owns project.yaml I/O, upward discovery, status/clone, and the project override layer;
it holds no rendering — the facade drives the pipeline and the run store records provenance.
There is deliberately no global "active project" state: a project is resolved per invocation
from the current directory (walking upward) or an explicit ``--project`` path, so concurrent
processes never share mutable open-project state (§8.3).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

from arcavex.kernel.api import AutomationPolicy, ProjectUIMetadata
from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.fsutil import atomic_write_text
from arcavex.services.library import Library, ResolvedTemplate, is_library_ref
from arcavex.services.project_locking import project_mutation_lock
from arcavex.services.template.loader import load_template, load_yaml

PROJECT_FILE = "project.yaml"
PROJECT_UI_FILE = "project.ui.yaml"

ProjectStatus = Literal["draft", "review", "approved", "published"]
_STATUSES: tuple[str, ...] = get_args(ProjectStatus)
_AUTOMATION_POLICY_KEYS = frozenset({"version", "mode", "extensions"})


class ProjectModel(BaseModel):
    """The ``project.yaml`` manifest — the tracked unit of a campaign (§5.2)."""

    model_config = ConfigDict(frozen=True)

    name: str
    template: str
    style: str | None = None
    locales: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    data: str | None = None
    # Optional per-project default render DPI: the project.yaml layer of the §6.3 precedence
    # chain (below a CLI --dpi / ARCAVEX_DPI, above config.toml). Unset renders each format at
    # its own declared canvas DPI.
    dpi: int | None = None
    status: ProjectStatus = "draft"
    tags: list[str] = Field(default_factory=list)
    automation: AutomationPolicy = Field(default_factory=AutomationPolicy)


@dataclass(frozen=True)
class Project:
    """A loaded project: its root directory and parsed manifest."""

    root: Path
    manifest: ProjectModel

    @property
    def project_file(self) -> Path:
        """Path to ``project.yaml``."""
        return self.root / PROJECT_FILE

    @property
    def outputs_dir(self) -> Path:
        """The ``outputs/`` directory holding recorded runs."""
        return self.root / "outputs"

    @property
    def overrides_dir(self) -> Path:
        """The ``overrides/`` directory holding project patch files."""
        return self.root / "overrides"

    @property
    def assets_dir(self) -> Path:
        """The project-local ``assets/`` directory."""
        return self.root / "assets"

    @property
    def data_path(self) -> Path | None:
        """The base data file path, or ``None`` when the project declares none."""
        return (self.root / self.manifest.data) if self.manifest.data else None

    @property
    def patch_path(self) -> Path:
        """The project override patch file ``overrides/<template>.patch.yaml`` (§5.4)."""
        return self.overrides_dir / f"{template_stem(self.manifest.template)}.patch.yaml"


def template_stem(ref: str) -> str:
    """Return the template name a project override file is keyed by (``name`` before ``@``)."""
    if is_library_ref(ref):
        return ref.partition("@")[0]
    p = Path(ref)
    return p.name if p.suffix == "" else p.stem


class ProjectService:
    """Creates, discovers, and mutates projects; resolves their pinned template."""

    def __init__(self, library: Library | None = None) -> None:
        """Bind to a :class:`Library` for resolving library template references."""
        self._library = library or Library()

    # -------------------------------------------------------------------- discovery
    def resolve(self, start: Path | None = None, override: Path | None = None) -> Project:
        """Resolve the active project from ``--project`` or by walking up from ``start`` (cwd).

        ``override`` (``--project``) wins and must name a directory containing ``project.yaml``.
        Otherwise discovery walks upward from ``start`` (default: cwd) to the filesystem root.
        No project found is a located ``ARC-PRJ-001``.
        """
        if override is not None:
            override = Path(override)
            candidate = override / PROJECT_FILE if override.is_dir() else override
            if candidate.name == PROJECT_FILE and candidate.is_file():
                return self.load(candidate.parent)
            raise DiagnosticError(
                diagnostic(
                    "ARC-PRJ-001",
                    f"No project.yaml under --project {override}",
                    file=str(override),
                    hint="Pass --project pointing at a directory that contains a project.yaml.",
                )
            )
        here = Path(start) if start is not None else Path.cwd()
        here = here.resolve()
        for directory in (here, *here.parents):
            if (directory / PROJECT_FILE).is_file():
                return self.load(directory)
        raise DiagnosticError(
            diagnostic(
                "ARC-PRJ-001",
                "No project found (no project.yaml in this or any parent directory)",
                hint="Run inside a project, pass --project <dir>, or create one with "
                "'arcavex project new'.",
            )
        )

    def load(self, project_dir: Path) -> Project:
        """Load and validate the ``project.yaml`` in ``project_dir`` (``ARC-PRJ-002`` on error)."""
        project_dir = Path(project_dir).resolve()
        raw = load_yaml(project_dir / PROJECT_FILE)
        if not isinstance(raw, dict):
            raise self._invalid(project_dir, "project.yaml is not a mapping")
        try:
            manifest = ProjectModel.model_validate(_manifest_validation_data(raw))
        except ValidationError as exc:
            raise self._invalid(project_dir, _first_error(exc)) from exc
        return Project(root=project_dir, manifest=manifest)

    # -------------------------------------------------------------------- creation
    def create(
        self,
        target: Path,
        name: str,
        template_ref: str,
        *,
        style: str | None = None,
        formats: list[str] | None = None,
        locales: list[str] | None = None,
    ) -> Project:
        """Scaffold a renderable project at ``target`` pinning ``template_ref`` (§5.2, §6.1.2).

        A library reference is resolved and pinned to an exact ``name@version`` so a recorded
        render never drifts; a filesystem path is stored relative to the project. Formats and
        locales default to the template's own declarations, and a starter data file is written
        from the template's own ``data.yaml`` when it ships one, or from ``preview_data`` when it
        does not, so the project renders immediately either way.
        """
        target = Path(target)
        if target.exists() and any(target.iterdir()):
            raise DiagnosticError(
                diagnostic(
                    "ARC-PRJ-003",
                    f"Project target is not empty: {target}",
                    file=str(target),
                    hint="Choose a new or empty directory for 'project new'.",
                )
            )
        pinned_ref, template_dir = self._pin_template(template_ref, target)
        source = load_template(template_dir)
        raw = source.raw
        tpl_formats = sorted(str(k) for k in (raw.get("formats") or {}))
        tpl_locales = sorted(str(k) for k in (raw.get("locales") or {}))
        preview = _plain(raw.get("preview_data") or {})

        manifest = ProjectModel(
            name=name,
            template=pinned_ref,
            style=style if style is not None else _template_style(raw),
            locales=locales if locales is not None else tpl_locales,
            formats=formats if formats is not None else tpl_formats,
            data=f"data/{name}.yaml",
            status="draft",
            tags=[],
        )
        target.mkdir(parents=True, exist_ok=True)
        (target / "assets").mkdir(exist_ok=True)
        (target / "overrides").mkdir(exist_ok=True)
        (target / "outputs").mkdir(exist_ok=True)
        (target / "data").mkdir(exist_ok=True)
        # A template's own data.yaml is real content; preview_data is a thumbnail of it. Seeding
        # from preview when both exist handed the author abbreviated strings in place of the copy
        # they had just written, with nothing said about the substitution.
        shipped = template_dir / "data.yaml" if template_dir.is_dir() else None
        if shipped is not None and shipped.is_file():
            loaded = _plain(load_yaml(shipped))
            starter = loaded if isinstance(loaded, dict) else {}
        else:
            starter = preview if isinstance(preview, dict) else {}
        _dump_yaml_atomic(target / f"data/{name}.yaml", starter)
        self._write_manifest(target, manifest)
        return Project(root=target, manifest=manifest)

    def save(self, project: Project) -> Project:
        """Write a project's manifest back to disk atomically and return the project."""
        self._write_manifest(project.root, project.manifest)
        return project

    def load_ui_metadata(self, project: Project) -> ProjectUIMetadata:
        """Read optional project-owned editor metadata without creating the sidecar."""
        path = project.root / PROJECT_UI_FILE
        if not path.is_file():
            return ProjectUIMetadata()
        raw = load_yaml(path)
        if not isinstance(raw, dict):
            raise _invalid_ui_metadata(path, "project.ui.yaml is not a mapping")
        try:
            return ProjectUIMetadata.model_validate(_plain(raw))
        except ValidationError as exc:
            raise _invalid_ui_metadata(path, _first_error(exc)) from exc

    def save_ui_metadata(
        self, project: Project, metadata: ProjectUIMetadata
    ) -> ProjectUIMetadata:
        """Atomically persist canonical project-owned editor metadata."""
        with project_mutation_lock(project.root):
            self.load(project.root)
            _dump_yaml_atomic(project.root / PROJECT_UI_FILE, _ui_metadata_dict(metadata))
        return metadata

    def save_automation_policy(
        self, project: Project, policy: AutomationPolicy
    ) -> Project:
        """Merge only automation into round-trip YAML, preserving unknown authored content."""
        with project_mutation_lock(project.root):
            path = project.root / PROJECT_FILE
            raw = load_yaml(path)
            if not isinstance(raw, dict):
                raise self._invalid(project.root, "project.yaml is not a mapping")
            existing = raw.get("automation")
            if isinstance(existing, dict):
                automation = existing
            else:
                automation: dict[str, Any] = {}
                raw["automation"] = automation

            if policy.mode == "unrestricted":
                _pop_default_automation_field(automation, "mode")
            else:
                automation["mode"] = policy.mode
            if policy.extensions == "unrestricted":
                _pop_default_automation_field(automation, "extensions")
            else:
                automation["extensions"] = policy.extensions

            has_unknown_fields = any(
                key not in _AUTOMATION_POLICY_KEYS for key in automation
            )
            if policy == AutomationPolicy() and not has_unknown_fields:
                raw.pop("automation", None)
            else:
                automation["version"] = policy.version
            _dump_yaml_atomic(path, raw)
            return self.load(project.root)

    def set_status(self, project: Project, status: str) -> Project:
        """Set the project's ``status`` (one of draft/review/approved/published) and persist it."""
        if status not in _STATUSES:
            raise DiagnosticError(
                diagnostic(
                    "ARC-PRJ-004",
                    f"Unknown project status {status!r}",
                    hint=f"Use one of: {', '.join(_STATUSES)}.",
                )
            )
        updated = project.manifest.model_copy(update={"status": status})
        self._write_manifest(project.root, updated)
        return Project(root=project.root, manifest=updated)

    def clone(self, project: Project, target: Path, new_name: str) -> Project:
        """Copy a project to ``target`` under ``new_name``, reset to draft, dropping ``outputs/``.

        Data, assets, and overrides carry over; recorded runs do not (a clone starts its own
        provenance history).
        """
        target = Path(target)
        if target.exists() and any(target.iterdir()):
            raise DiagnosticError(
                diagnostic(
                    "ARC-PRJ-003",
                    f"Clone target is not empty: {target}",
                    file=str(target),
                    hint="Choose a new or empty directory to clone into.",
                )
            )
        target.mkdir(parents=True, exist_ok=True)
        for sub in ("data", "assets", "overrides"):
            src = project.root / sub
            if src.is_dir():
                shutil.copytree(src, target / sub)
        (target / "outputs").mkdir(exist_ok=True)
        cloned = project.manifest.model_copy(update={"name": new_name, "status": "draft"})
        self._write_manifest(target, cloned)
        return Project(root=target, manifest=cloned)

    # ------------------------------------------------------------------- template + patch
    def resolve_template(self, project: Project) -> tuple[Path, str, bool]:
        """Return ``(template_dir, ref, is_library)`` for a project's pinned template."""
        ref = project.manifest.template
        if is_library_ref(ref):
            resolved: ResolvedTemplate = self._library.resolve(ref)
            return resolved.path, f"{resolved.name}@{resolved.version}", True
        return (project.root / ref).resolve(), ref, False

    def load_project_patch(self, project: Project) -> tuple[list[Any] | None, Path | None]:
        """Return the project override patch ops and their file, or ``(None, None)`` if absent."""
        patch_file = project.patch_path
        if not patch_file.is_file():
            return None, None
        raw = load_yaml(patch_file)
        if not isinstance(raw, list):
            raise DiagnosticError(
                diagnostic(
                    "ARC-PRJ-002",
                    f"Project override {patch_file.name} must be a list of patch operations",
                    file=str(patch_file),
                    hint="Write the override as a YAML list of set/remove/insert operations.",
                )
            )
        return list(raw), patch_file

    def render_targets(
        self,
        project: Project,
        formats: list[str] | None = None,
        locales: list[str] | None = None,
    ) -> list[tuple[str, str | None]]:
        """Return the ``(format, locale)`` render targets for a project (their cross product).

        Defaults to the project's declared formats × locales; an empty locale list renders once
        with no locale (``None``). Explicit ``formats``/``locales`` narrow the set.
        """
        use_formats = formats if formats is not None else project.manifest.formats
        use_locales = locales if locales is not None else project.manifest.locales
        locale_axis: list[str | None] = list(use_locales) if use_locales else [None]
        return [(fmt, loc) for fmt in use_formats for loc in locale_axis]

    # -------------------------------------------------------------------- internals
    def _pin_template(self, template_ref: str, project_target: Path) -> tuple[str, Path]:
        if is_library_ref(template_ref):
            resolved = self._library.resolve(template_ref)
            return f"{resolved.name}@{resolved.version}", resolved.path
        template_path = Path(template_ref).resolve()
        root = _resolve_template_dir(template_path)
        # Store the path relative to the project so the project stays relocatable as a tree.
        rel = os.path.relpath(root, project_target.resolve())
        return rel.replace(os.sep, "/"), root

    def _write_manifest(self, root: Path, manifest: ProjectModel) -> None:
        _dump_yaml_atomic(root / PROJECT_FILE, _manifest_dict(manifest))

    def _invalid(self, project_dir: Path, detail: str) -> DiagnosticError:
        return DiagnosticError(
            diagnostic(
                "ARC-PRJ-002",
                f"Invalid project manifest: {detail}",
                file=str(project_dir / PROJECT_FILE),
                hint="A project.yaml needs at least 'name' and 'template'.",
            )
        )


def _resolve_template_dir(path: Path) -> Path:
    """Return the template directory for a path (its parent if a template.yaml file was given)."""
    if path.is_dir():
        return path
    if path.is_file():
        return path.parent
    raise DiagnosticError(
        diagnostic(
            "ARC-PRJ-002",
            f"Template path does not exist: {path}",
            file=str(path),
            hint="Pass a template directory or an existing library 'name@version'.",
        )
    )


def _manifest_dict(manifest: ProjectModel) -> dict[str, Any]:
    """Render a manifest as an ordered plain dict for a clean project.yaml."""
    out: dict[str, Any] = {
        "name": manifest.name,
        "template": manifest.template,
        "style": manifest.style,
        "locales": list(manifest.locales),
        "formats": list(manifest.formats),
        "data": manifest.data,
        "status": manifest.status,
        "tags": list(manifest.tags),
    }
    # Only persist an explicit per-project DPI, so a scaffolded project.yaml stays clean.
    if manifest.dpi is not None:
        out["dpi"] = manifest.dpi
    if manifest.automation != AutomationPolicy():
        policy: dict[str, Any] = {"version": manifest.automation.version}
        if manifest.automation.mode != "unrestricted":
            policy["mode"] = manifest.automation.mode
        if manifest.automation.extensions != "unrestricted":
            policy["extensions"] = manifest.automation.extensions
        out["automation"] = policy
    return out


def _ui_metadata_dict(metadata: ProjectUIMetadata) -> dict[str, Any]:
    """Render editor metadata without serializing optional/default noise."""
    layers: dict[str, Any] = {}
    for layer_id, layer in metadata.layers.items():
        value: dict[str, Any] = {}
        if layer.display_name is not None:
            value["display_name"] = layer.display_name
        if layer.locked:
            value["locked"] = True
        if layer.color is not None:
            value["color"] = layer.color
        layers[layer_id] = value
    workspace = metadata.workspace.model_dump(
        mode="python", exclude_defaults=True, exclude_none=True
    )
    return {"version": metadata.version, "layers": layers, "workspace": workspace}


def _invalid_ui_metadata(path: Path, detail: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-PRJ-008",
            f"Invalid project UI metadata: {detail}",
            file=str(path),
            hint=(
                "Use version 1 with layer display_name/locked/#RRGGBB color metadata and "
                "supported project-local workspace fields."
            ),
        )
    )


def _template_style(raw: Any) -> str | None:
    style = raw.get("style") if isinstance(raw, dict) else None
    return str(style) if isinstance(style, str) else None


def _dump_yaml_atomic(path: Path, data: Any) -> None:
    import io

    from ruamel.yaml import YAML

    buffer = io.StringIO()
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    yaml.dump(data, buffer)
    atomic_write_text(path, buffer.getvalue())


def _plain(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


def _manifest_validation_data(raw: dict[Any, Any]) -> dict[str, Any]:
    """Validate known persisted policy axes while tolerating forward metadata."""
    data: dict[str, Any] = _plain(raw)
    automation = data.get("automation")
    if isinstance(automation, dict):
        data["automation"] = {
            key: value
            for key, value in automation.items()
            if key in _AUTOMATION_POLICY_KEYS
        }
    return data


def _pop_default_automation_field(
    automation: dict[str, Any], field: str
) -> None:
    """Remove a default-valued axis without dropping a following unknown key's comment."""
    comments = getattr(automation, "ca", None)
    ordered_keys = list(automation)
    if comments is not None and field in automation:
        index = ordered_keys.index(field)
        following = ordered_keys[index + 1] if index + 1 < len(ordered_keys) else None
        attached = comments.items.get(field)
        token = attached[2] if attached and len(attached) > 2 else None
        if (
            token is not None
            and following is not None
            and following not in _AUTOMATION_POLICY_KEYS
        ):
            preserved = _standalone_comment_tokens(
                token, indent=automation.lc.key(following)[1]
            )
            if preserved:
                destination = comments.items.setdefault(
                    following, [None, None, None, None]
                )
                if destination[1] is None:
                    destination[1] = []
                destination[1].extend(preserved)
            attached[2] = None
    automation.pop(field, None)


def _standalone_comment_tokens(
    token: CommentToken, *, indent: int
) -> list[CommentToken]:
    """Split an axis EOL token into marked pre-key comments owned by the next field."""
    value = token.value
    if value.startswith("#"):
        _, newline, value = value.partition("\n")
        if not newline:
            return []
    elif value.startswith("\r\n"):
        value = value[2:]
    elif value.startswith("\n"):
        value = value[1:]
    else:
        return []

    lines = value.splitlines(keepends=True)
    mark = CommentMark(indent)
    preserved: list[CommentToken] = []
    while lines and not lines[0].strip(" \t\r\n"):
        preserved.append(CommentToken(lines.pop(0), mark))
    if lines:
        lines[0] = lines[0].lstrip(" ")
        preserved.append(CommentToken("".join(lines), mark))
    return preserved


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    return f"{loc}: {err.get('msg', 'invalid')}" if loc else err.get("msg", "invalid")

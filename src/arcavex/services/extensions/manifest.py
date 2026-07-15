"""The ``extension.toml`` manifest: model, parser, and engine/IR compatibility (spec §3.3).

A local extension is a directory holding ``extension.toml`` plus its Python entry modules. The
manifest names the extension, the minimum engine and IR versions it targets, and a list of
components (a package may register several — hence a component list, not a single kind/entry
pair). Parsing produces located ``ARC-EXT`` diagnostics rather than raising raw ``TOMLDecodeError``
so a malformed manifest reads like every other authoring error.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.sdk.registration import COMPONENT_KINDS

MANIFEST_NAME = "extension.toml"

# A component name: lowercase words joined by hyphens/underscores, matching the authoring
# vocabulary built-ins use (e.g. "paper-texture"). An extension name follows the same rule.
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*([-_][a-z0-9]+)*$")
# An entry point "module:Class" — a dotted module path and a class identifier.
_ENTRY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ComponentSpec:
    """One component a manifest declares: its kind, registered name, and entry point."""

    kind: str
    name: str
    entry: str  # "module:Class" relative to the extension package

    @property
    def module(self) -> str:
        """The entry module path (before the colon)."""
        return self.entry.split(":", 1)[0]

    @property
    def class_name(self) -> str:
        """The entry class name (after the colon)."""
        return self.entry.split(":", 1)[1]


@dataclass(frozen=True)
class ExtensionManifest:
    """A parsed ``extension.toml``: identity, compat floors, and the component list."""

    name: str
    version: str
    ir_min: str
    engine_min: str
    components: tuple[ComponentSpec, ...]


def parse_version(text: str) -> tuple[int, ...]:
    """Return the leading dotted numeric components of a version as an int tuple.

    A pre-release/build suffix (``0.1.0.dev0`` -> ``(0, 1, 0)``, ``0.1`` -> ``(0, 1)``) is
    dropped at the first non-numeric segment, so an engine of ``0.1.0.dev0`` satisfies an
    ``engine_min`` of ``0.1``. An empty or non-numeric string yields ``(0,)``.
    """
    parts: list[int] = []
    for segment in text.strip().split("."):
        if segment.isdigit():
            parts.append(int(segment))
        else:
            break
    return tuple(parts) or (0,)


def version_at_least(current: str, minimum: str) -> bool:
    """Whether ``current`` is >= ``minimum`` comparing padded leading-numeric version tuples."""
    cur = parse_version(current)
    low = parse_version(minimum)
    width = max(len(cur), len(low))
    cur += (0,) * (width - len(cur))
    low += (0,) * (width - len(low))
    return cur >= low


def manifest_path(extension_dir: Path) -> Path:
    """Return the ``extension.toml`` path inside an extension directory."""
    return Path(extension_dir) / MANIFEST_NAME


def parse_manifest(extension_dir: Path) -> tuple[ExtensionManifest | None, list[Diagnostic]]:
    """Parse ``<extension_dir>/extension.toml`` into a manifest plus located diagnostics.

    Returns ``(manifest, diagnostics)``; ``manifest`` is ``None`` when a structural error made
    the manifest unusable. Field-level problems accumulate so an author sees every mistake in one
    pass rather than one-at-a-time.
    """
    path = manifest_path(extension_dir)
    if not path.is_file():
        return None, [
            diagnostic(
                "ARC-EXT-010",
                f"Extension manifest not found: {path}",
                file=str(path),
                hint=f"An extension directory must contain an {MANIFEST_NAME} file.",
            )
        ]
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return None, [
            diagnostic(
                "ARC-EXT-011",
                f"Extension manifest is not valid TOML: {exc}",
                file=str(path),
                hint="Fix the TOML syntax; the parser reports the offending location.",
            )
        ]
    return _build_manifest(raw, path)


def _build_manifest(
    raw: dict[str, object], path: Path
) -> tuple[ExtensionManifest | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    name = _require_str(raw, "name", path, diagnostics)
    version = _require_str(raw, "version", path, diagnostics)
    ir_min = _require_str(raw, "ir_min", path, diagnostics)
    engine_min = _require_str(raw, "engine_min", path, diagnostics)

    if name is not None and not _NAME_RE.match(name):
        diagnostics.append(
            diagnostic(
                "ARC-EXT-011",
                f"Extension name {name!r} is not a valid identifier",
                file=str(path),
                keypath="name",
                hint="Use lowercase words joined by '-' or '_', e.g. 'print-effects'.",
            )
        )

    components, comp_diags = _parse_components(raw.get("components"), path)
    diagnostics.extend(comp_diags)

    if name is None or version is None or ir_min is None or engine_min is None:
        return None, diagnostics
    if not components and not comp_diags:
        diagnostics.append(
            diagnostic(
                "ARC-EXT-012",
                "Extension manifest declares no components",
                file=str(path),
                keypath="components",
                hint="Add at least one [[components]] entry with kind, name, and entry.",
            )
        )
        return None, diagnostics
    manifest = ExtensionManifest(
        name=name,
        version=version,
        ir_min=ir_min,
        engine_min=engine_min,
        components=tuple(components),
    )
    return manifest, diagnostics


def _parse_components(
    raw_components: object, path: Path
) -> tuple[list[ComponentSpec], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if raw_components is None:
        return [], []
    if not isinstance(raw_components, list):
        return [], [
            diagnostic(
                "ARC-EXT-011",
                "'components' must be a list of [[components]] tables",
                file=str(path),
                keypath="components",
                hint="Declare each component as a [[components]] table.",
            )
        ]
    specs: list[ComponentSpec] = []
    seen: set[tuple[str, str]] = set()
    for i, entry in enumerate(raw_components):
        kp = f"components[{i}]"
        if not isinstance(entry, dict):
            diagnostics.append(
                diagnostic(
                    "ARC-EXT-011",
                    "Each component must be a table with kind, name, and entry",
                    file=str(path),
                    keypath=kp,
                    hint="Use a [[components]] table.",
                )
            )
            continue
        spec = _parse_component(entry, path, kp, diagnostics)
        if spec is None:
            continue
        key = (spec.kind, spec.name)
        if key in seen:
            diagnostics.append(
                diagnostic(
                    "ARC-EXT-014",
                    f"Duplicate {spec.kind} component {spec.name!r} in this manifest",
                    file=str(path),
                    keypath=kp,
                    hint="Component names are unique per kind; rename one of the two.",
                )
            )
            continue
        seen.add(key)
        specs.append(spec)
    return specs, diagnostics


def _parse_component(
    entry: dict[str, object], path: Path, kp: str, diagnostics: list[Diagnostic]
) -> ComponentSpec | None:
    kind = _require_field_str(entry, "kind", path, kp, diagnostics)
    name = _require_field_str(entry, "name", path, kp, diagnostics)
    entry_point = _require_field_str(entry, "entry", path, kp, diagnostics)
    if kind is not None and kind not in COMPONENT_KINDS:
        allowed = ", ".join(COMPONENT_KINDS)
        diagnostics.append(
            diagnostic(
                "ARC-EXT-013",
                f"Unknown component kind {kind!r}",
                file=str(path),
                keypath=f"{kp}.kind",
                hint=f"kind must be one of: {allowed}.",
            )
        )
        kind = None
    if name is not None and not _NAME_RE.match(name):
        diagnostics.append(
            diagnostic(
                "ARC-EXT-011",
                f"Component name {name!r} is not a valid identifier",
                file=str(path),
                keypath=f"{kp}.name",
                hint="Use lowercase words joined by '-' or '_', e.g. 'paper-texture'.",
            )
        )
        name = None
    if entry_point is not None and not _ENTRY_RE.match(entry_point):
        diagnostics.append(
            diagnostic(
                "ARC-EXT-011",
                f"Component entry {entry_point!r} is not 'module:Class'",
                file=str(path),
                keypath=f"{kp}.entry",
                hint="Write entry as 'module:Class', e.g. 'effects:PaperTexture'.",
            )
        )
        entry_point = None
    if kind is None or name is None or entry_point is None:
        return None
    return ComponentSpec(kind=kind, name=name, entry=entry_point)


def _require_str(
    raw: dict[str, object], key: str, path: Path, diagnostics: list[Diagnostic]
) -> str | None:
    value = raw.get(key)
    if value is None:
        diagnostics.append(
            diagnostic(
                "ARC-EXT-012",
                f"Extension manifest is missing required field {key!r}",
                file=str(path),
                keypath=key,
                hint=f"Add a top-level '{key} = ...' entry to {MANIFEST_NAME}.",
            )
        )
        return None
    if not isinstance(value, str):
        diagnostics.append(
            diagnostic(
                "ARC-EXT-011",
                f"Manifest field {key!r} must be a string",
                file=str(path),
                keypath=key,
                hint=f"Quote the value, e.g. {key} = \"0.1\".",
            )
        )
        return None
    return value


def _require_field_str(
    entry: dict[str, object], key: str, path: Path, kp: str, diagnostics: list[Diagnostic]
) -> str | None:
    value = entry.get(key)
    if value is None:
        diagnostics.append(
            diagnostic(
                "ARC-EXT-012",
                f"Component is missing required field {key!r}",
                file=str(path),
                keypath=f"{kp}.{key}",
                hint=f"Add '{key} = ...' to the component table.",
            )
        )
        return None
    if not isinstance(value, str):
        diagnostics.append(
            diagnostic(
                "ARC-EXT-011",
                f"Component field {key!r} must be a string",
                file=str(path),
                keypath=f"{kp}.{key}",
                hint="Quote the value.",
            )
        )
        return None
    return value


__all__ = [
    "MANIFEST_NAME",
    "ComponentSpec",
    "ExtensionManifest",
    "manifest_path",
    "parse_manifest",
    "parse_version",
    "version_at_least",
]

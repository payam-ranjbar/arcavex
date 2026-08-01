"""Style packs: named, versioned bundles of palettes, fonts, presets, and role defaults.

A style pack (spec §4.1.3) is a YAML file supplying reusable design tokens a template opts into
with ``style:``. Templates reference a library pack by ``name@version`` (resolved from
``library-seed/styles`` and ``$ARCAVEX_HOME/styles``) or a local file by ``./path.yaml``. Packs
supply, and this module exposes to the compiler:

* ``palettes`` — named colour lists, addressable in expressions as ``{{ palette.<name>[i] }}``;
* ``fonts`` — role → family-stack defaults;
* ``effect_presets`` — named ``{name, params}`` effect configurations nodes reference by name;
* ``roles`` — ``heading``/``body``/``accent`` default style fields for text nodes.

Resolution is deliberately narrow: reading versioned directories is enough for v1 (full library
publishing is Phase 4). Unknown packs, presets, and roles are located errors that list what is
available, never silent fallbacks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.template.loader import load_yaml, node_line

_STYLE_KEYS = {
    "version", "palettes", "fonts", "effect_presets", "shape_presets", "roles",
}


@dataclass(frozen=True)
class StylePack:
    """A loaded style pack.

    ``source`` is the file it came from (for diagnostics). ``palettes`` values are the raw
    authored colour strings so expressions receive exactly what the pack declared.
    """

    name: str
    version: str
    source: Path
    palettes: dict[str, list[str]] = field(default_factory=dict)
    fonts: dict[str, list[str]] = field(default_factory=dict)
    effect_presets: dict[str, dict[str, Any]] = field(default_factory=dict)
    shape_presets: dict[str, dict[str, Any]] = field(default_factory=dict)
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)

    def preset(self, name: str, *, file: str, keypath: str, line: int | None) -> dict[str, Any]:
        """Return the effect preset ``name`` or raise a located error listing the available ones."""
        if name not in self.effect_presets:
            available = ", ".join(sorted(self.effect_presets)) or "(none)"
            raise DiagnosticError(
                diagnostic(
                    "ARC-STY-010",
                    f"Style {self.name!r} has no effect preset {name!r}",
                    file=file, keypath=keypath, line=line,
                    hint=f"Presets in this style: {available}.",
                )
            )
        return self.effect_presets[name]

    def role(self, name: str, *, file: str, keypath: str, line: int | None) -> dict[str, Any]:
        """Return the role defaults for ``name`` or raise a located error listing the roles."""
        if name not in self.roles:
            available = ", ".join(sorted(self.roles)) or "(none)"
            raise DiagnosticError(
                diagnostic(
                    "ARC-STY-011",
                    f"Style {self.name!r} has no role {name!r}",
                    file=file, keypath=keypath, line=line,
                    hint=f"Roles in this style: {available}.",
                )
            )
        return self.roles[name]


def find_style_dirs() -> list[Path]:
    """Return the ordered directories style packs are read from.

    The packaged ``arcavex/_bundled/styles`` directory (shipped in the wheel via
    ``force-include``) first, then the in-repo ``library-seed/styles`` located by walking up to
    the ``pyproject.toml`` marker, then ``$ARCAVEX_HOME/styles`` when set — mirroring the
    bundled-font search exactly. The packaged directory is what makes an engine installed
    outside a source checkout (a wheel, or a frozen binary) resolve the seeded packs at all;
    the marker walk alone finds nothing there.
    """
    dirs: list[Path] = []
    packaged = _packaged_styles_dir()
    if packaged is not None:
        dirs.append(packaged)
    marker = _find_repo_root()
    if marker is not None:
        seed = marker / "library-seed" / "styles"
        if seed.is_dir():
            dirs.append(seed)
    home = os.environ.get("ARCAVEX_HOME")
    if home:
        home_styles = Path(home) / "styles"
        if home_styles.is_dir():
            dirs.append(home_styles)
    return dirs


class StyleResolver:
    """Loads style packs from the library or a local file, and lists/inspects them."""

    def __init__(self, style_dirs: list[Path] | None = None) -> None:
        """Bind the resolver to its search directories (defaults to :func:`find_style_dirs`)."""
        self._dirs = style_dirs if style_dirs is not None else find_style_dirs()

    def resolve(
        self,
        ref: str,
        template_dir: Path,
        *,
        file: str | None = None,
        keypath: str | None = None,
        line: int | None = None,
    ) -> StylePack:
        """Resolve a ``style:`` reference to a loaded pack.

        A ref containing a path separator or ending in ``.yaml`` is a template-relative file;
        anything else is a ``name`` or ``name@version`` library reference. ``file``/``keypath``/
        ``line`` locate the offending ``style:`` reference in the source, so a missing pack or
        file is a *located* error like the preset/role diagnostics (CR-3/DX-7).
        """
        loc = {"file": file, "keypath": keypath, "line": line}
        if ref.endswith(".yaml") or ref.startswith((".", "/", "~")) or "/" in ref or "\\" in ref:
            path = (template_dir / ref).resolve()
            if not path.is_file():
                raise DiagnosticError(
                    diagnostic(
                        "ARC-STY-001",
                        f"Style file not found: {ref}",
                        hint="Give a path relative to the template, or a 'name@version' library "
                        "reference.",
                        **loc,
                    )
                )
            name = path.stem
            return self._load(path, name)
        name, _, version = ref.partition("@")
        path = self._find_library(name, version or None, ref, loc)
        return self._load(path, name)

    def list_packs(self) -> list[StylePack]:
        """Return every discoverable pack, sorted by ``(name, version)``."""
        packs: list[StylePack] = []
        for base in self._dirs:
            for pack_dir in sorted(p for p in base.iterdir() if p.is_dir()):
                for yaml_file in sorted(pack_dir.glob("*.yaml")):
                    packs.append(self._load(yaml_file, pack_dir.name))
        return sorted(packs, key=lambda p: (p.name, p.version))

    def inspect(self, ref: str) -> StylePack:
        """Load a pack by library reference for ``style inspect`` (no template context)."""
        name, _, version = ref.partition("@")
        path = self._find_library(name, version or None, ref)
        return self._load(path, name)

    # -------------------------------------------------------------------- internals
    def _find_library(
        self,
        name: str,
        version: str | None,
        ref: str,
        loc: dict[str, str | int | None] | None = None,
    ) -> Path:
        loc = loc or {}
        candidates: list[tuple[str, Path]] = []
        for base in self._dirs:
            pack_dir = base / name
            if not pack_dir.is_dir():
                continue
            for yaml_file in pack_dir.glob("*.yaml"):
                candidates.append((yaml_file.stem, yaml_file))
        if not candidates:
            raise DiagnosticError(
                diagnostic(
                    "ARC-STY-001",
                    f"Unknown style pack {ref!r}",
                    hint=f"Available styles: {self._available_names() or '(none)'}.",
                    **loc,
                )
            )
        if version is not None:
            exact = [p for v, p in candidates if v == version]
            if exact:
                return exact[0]
            prefixed = sorted(
                (v, p) for v, p in candidates if v.startswith(version)
            )
            if prefixed:
                return prefixed[-1][1]
            available = ", ".join(sorted(v for v, _ in candidates))
            raise DiagnosticError(
                diagnostic(
                    "ARC-STY-001",
                    f"Style {name!r} has no version matching {version!r}",
                    hint=f"Available versions: {available}.",
                    **loc,
                )
            )
        # No version requested: take the highest.
        return sorted(candidates)[-1][1]

    def _available_names(self) -> str:
        names: set[str] = set()
        for base in self._dirs:
            if base.is_dir():
                names |= {p.name for p in base.iterdir() if p.is_dir()}
        return ", ".join(sorted(names))

    def _load(self, path: Path, name: str) -> StylePack:
        raw = load_yaml(path)
        if not isinstance(raw, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-STY-002",
                    f"Style pack {name!r} is not a mapping",
                    file=str(path),
                    hint="A style pack is a YAML mapping with 'version', 'palettes', 'fonts', etc.",
                )
            )
        unknown = set(raw) - _STYLE_KEYS
        if unknown:
            raise DiagnosticError(
                diagnostic(
                    "ARC-STY-002",
                    f"Style pack {name!r} has unknown keys: {', '.join(sorted(unknown))}",
                    file=str(path),
                    line=node_line(raw),
                    hint=f"Style packs support: {', '.join(sorted(_STYLE_KEYS))}.",
                )
            )
        return StylePack(
            name=name,
            version=str(raw.get("version", "0")),
            source=path,
            palettes=_str_lists(raw.get("palettes")),
            fonts=_str_lists(raw.get("fonts")),
            effect_presets=_dict_of_dicts(raw.get("effect_presets")),
            shape_presets=_dict_of_dicts(raw.get("shape_presets")),
            roles=_dict_of_dicts(raw.get("roles")),
        )


def _packaged_styles_dir() -> Path | None:
    """Return the wheel-bundled style directory beside the installed package, if present."""
    # ``arcavex/_bundled/styles`` is created by the wheel's force-include; it is absent in a raw
    # source checkout, where the repo-root ``library-seed/styles`` is used instead.
    packaged = Path(__file__).resolve().parents[1] / "_bundled" / "styles"
    return packaged if packaged.is_dir() else None


def _find_repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _str_lists(value: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if isinstance(value, dict):
        for key, entry in value.items():
            if isinstance(entry, (list, tuple)):
                out[str(key)] = [str(v) for v in entry]
            elif entry is not None:
                out[str(key)] = [str(entry)]
    return out


def _dict_of_dicts(value: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(value, dict):
        for key, entry in value.items():
            if isinstance(entry, dict):
                out[str(key)] = {str(k): _plain(v) for k, v in entry.items()}
    return out


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value

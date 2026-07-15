"""Runtime configuration precedence (spec §6.3).

A small resolver for settings that a user can pin at several levels. The precedence chain,
highest first, is: an explicit CLI flag, an ``ARCAVEX_*`` environment variable, the project's
``project.yaml``, a ``config.toml`` in the Arcavex home, then the built-in default. Only one
setting is wired today — the default render DPI — but it is resolvable through the full chain,
and ``doctor`` reports which layer a value came from so the precedence is inspectable.

``config.toml`` lives at ``$ARCAVEX_HOME/config.toml`` (or ``~/.arcavex/config.toml`` when
``ARCAVEX_HOME`` is unset), the same home the versioned library and caches use. Indexes and
caches are disposable; this file is user-authored configuration, so a malformed file is a
located problem rather than a silent reset — but since config is optional, a missing file is
simply "no config layer".
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arcavex.services.fsutil import home_dir

CONFIG_NAME = "config.toml"
_DPI_ENV = "ARCAVEX_DPI"


@dataclass(frozen=True)
class Resolved:
    """A resolved setting value plus the precedence layer it came from."""

    value: int | None
    source: str  # "cli" | "env ARCAVEX_DPI" | "project.yaml" | "config.toml" | "default"


class RuntimeConfig:
    """Resolves runtime settings through the CLI → env → project → config.toml → default chain."""

    def __init__(
        self, *, env: dict[str, str] | None = None, config: dict[str, Any] | None = None
    ) -> None:
        """Bind an environment mapping and a parsed ``config.toml`` (default to the process)."""
        self._env = env if env is not None else dict(os.environ)
        self._config = config if config is not None else {}

    @classmethod
    def load(cls, *, env: dict[str, str] | None = None) -> RuntimeConfig:
        """Load config from the home ``config.toml`` (tolerant of an absent file)."""
        environ = env if env is not None else dict(os.environ)
        return cls(env=environ, config=_read_config(config_path(environ)))

    @property
    def raw(self) -> dict[str, Any]:
        """Return the parsed ``config.toml`` mapping (for section-scoped resolvers)."""
        return self._config

    def resolve_cache_bytes(self, default: int) -> int:
        """Resolve the derived-asset cache byte budget from ``[cache].derived_bytes`` (§4.7)."""
        section = self._config.get("cache")
        if isinstance(section, dict):
            value = _as_positive_int(section.get("derived_bytes"))
            if value is not None:
                return value
        return default

    def resolve_dpi(self, cli: int | None = None, project: int | None = None) -> Resolved:
        """Resolve the effective default DPI through the full precedence chain.

        ``None`` at every layer means "no override" — each format renders at its own declared
        canvas DPI (the built-in default). A resolved value overrides that per-format DPI.
        """
        if cli is not None:
            return Resolved(cli, "cli")
        env_val = self._env.get(_DPI_ENV)
        if env_val:
            parsed = _as_positive_int(env_val)
            if parsed is not None:
                return Resolved(parsed, f"env {_DPI_ENV}")
        if project is not None:
            return Resolved(project, "project.yaml")
        config_val = _as_positive_int(_render_section(self._config).get("dpi"))
        if config_val is not None:
            return Resolved(config_val, CONFIG_NAME)
        return Resolved(None, "default")


def config_path(env: dict[str, str] | None = None) -> Path:
    """Return the ``config.toml`` path under the Arcavex home."""
    environ = env if env is not None else dict(os.environ)
    home = Path(environ["ARCAVEX_HOME"]) if environ.get("ARCAVEX_HOME") else home_dir()
    return home / CONFIG_NAME


def _read_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        # Config is optional and disposable to the run; a broken file must not wedge rendering.
        return {}


def _render_section(config: dict[str, Any]) -> dict[str, Any]:
    section = config.get("render")
    return section if isinstance(section, dict) else {}


def _as_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

"""Added-extension state: ``$ARCAVEX_HOME/extensions/state.toml`` (spec §3.3, §8.3).

An added extension lives as a copied source tree under
``$ARCAVEX_HOME/extensions/sources/<name>/`` and a record in ``state.toml`` carrying its version
and whether it is enabled. The lifecycle is ``add → validate → disabled → enable``: ``add`` writes
a *disabled* record, ``enable``/``disable`` flip the flag, and the loader only registers enabled
extensions at process start — so disabling takes effect on the next start (spec §3.3). State
writes take the shared cross-process lock (spec §8.3) so two ``ext`` commands never corrupt it.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from arcavex.services.fsutil import atomic_write_text, file_lock, home_dir

STATE_NAME = "state.toml"


@dataclass(frozen=True)
class ExtensionRecord:
    """One added extension's state row: its name, version, and enabled flag."""

    name: str
    version: str
    enabled: bool


def extensions_home(env: dict[str, str] | None = None) -> Path:
    """Return ``$ARCAVEX_HOME/extensions`` (the extension state + sources root)."""
    environ = env if env is not None else dict(os.environ)
    home = Path(environ["ARCAVEX_HOME"]) if environ.get("ARCAVEX_HOME") else home_dir()
    return home / "extensions"


def sources_dir(env: dict[str, str] | None = None) -> Path:
    """Return the directory holding copied extension source trees."""
    return extensions_home(env) / "sources"


def source_path(name: str, env: dict[str, str] | None = None) -> Path:
    """Return the copied-source directory for one added extension."""
    return sources_dir(env) / name


def state_path(env: dict[str, str] | None = None) -> Path:
    """Return the ``state.toml`` path."""
    return extensions_home(env) / STATE_NAME


class ExtensionState:
    """Reads and writes the added-extension records in ``state.toml`` under a cross-process lock."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        """Bind the environment used to resolve the Arcavex home (defaults to the process)."""
        self._env = env

    def _path(self) -> Path:
        return state_path(self._env)

    def records(self) -> list[ExtensionRecord]:
        """Return every added extension's record, sorted by name (a stable, deterministic order)."""
        path = self._path()
        if not path.is_file():
            return []
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return []
        table = raw.get("extensions")
        if not isinstance(table, dict):
            return []
        out: list[ExtensionRecord] = []
        for name, row in table.items():
            if not isinstance(row, dict):
                continue
            out.append(
                ExtensionRecord(
                    name=str(name),
                    version=str(row.get("version", "0.0.0")),
                    enabled=bool(row.get("enabled", False)),
                )
            )
        return sorted(out, key=lambda r: r.name)

    def get(self, name: str) -> ExtensionRecord | None:
        """Return one extension's record, or ``None`` if it has not been added."""
        return next((r for r in self.records() if r.name == name), None)

    def add(self, name: str, version: str, *, enabled: bool = False) -> ExtensionRecord:
        """Write (or replace) a record for ``name``; new adds are disabled by default."""
        record = ExtensionRecord(name=name, version=version, enabled=enabled)
        with file_lock(self._lock_path()):
            records = {r.name: r for r in self.records()}
            records[name] = record
            self._write(list(records.values()))
        return record

    def set_enabled(self, name: str, enabled: bool) -> ExtensionRecord | None:
        """Flip an extension's enabled flag; returns the updated record or ``None`` if unknown."""
        with file_lock(self._lock_path()):
            records = {r.name: r for r in self.records()}
            existing = records.get(name)
            if existing is None:
                return None
            updated = replace(existing, enabled=enabled)
            records[name] = updated
            self._write(list(records.values()))
            return updated

    def remove(self, name: str) -> bool:
        """Drop an extension's record; returns whether it existed."""
        with file_lock(self._lock_path()):
            records = {r.name: r for r in self.records()}
            if name not in records:
                return False
            del records[name]
            self._write(list(records.values()))
            return True

    def _lock_path(self) -> Path:
        return extensions_home(self._env) / ".state.lock"

    def _write(self, records: list[ExtensionRecord]) -> None:
        atomic_write_text(self._path(), _serialize(records))


def _serialize(records: list[ExtensionRecord]) -> str:
    """Serialize records to TOML deterministically (sorted by name), one table each."""
    lines: list[str] = [
        "# Arcavex extension state (managed by 'arcavex ext'). Lists added extensions and",
        "# whether each is enabled; the loader registers only enabled extensions at start.",
        "",
    ]
    for record in sorted(records, key=lambda r: r.name):
        lines.append(f"[extensions.{record.name}]")
        lines.append(f'version = "{record.version}"')
        lines.append(f"enabled = {'true' if record.enabled else 'false'}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "STATE_NAME",
    "ExtensionRecord",
    "ExtensionState",
    "extensions_home",
    "source_path",
    "sources_dir",
    "state_path",
]

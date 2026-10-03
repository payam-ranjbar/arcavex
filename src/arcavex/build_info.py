"""Build identity shared by CLI, doctor, skill payloads, and the desktop handshake."""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
from pathlib import Path


def engine_version() -> str:
    try:
        return importlib.metadata.version("arcavex")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


def build_commit(*, source: bool = False) -> str | None:
    """Prefer embedded release identity; optionally inspect a real source checkout."""
    metadata = Path(__file__).parent / "_bundled" / "build.json"
    if metadata.is_file():
        try:
            value = json.loads(metadata.read_text(encoding="utf-8")).get("commit")
            if isinstance(value, str) and value:
                return value
        except (OSError, ValueError, AttributeError):
            pass
    if value := os.environ.get("ARCAVEX_BUILD_COMMIT"):
        return value
    if source:
        root = Path(__file__).resolve().parents[2]
        if (root / ".git").exists() and (root / "src" / "arcavex").is_dir():
            try:
                commit = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    cwd=root,
                    text=True,
                    timeout=2,
                    stderr=subprocess.DEVNULL,
                ).strip()
                dirty = subprocess.check_output(
                    ["git", "status", "--porcelain", "--untracked-files=no"],
                    cwd=root,
                    text=True,
                    timeout=2,
                    stderr=subprocess.DEVNULL,
                ).strip()
                return commit + ("-dirty" if dirty else "")
            except (OSError, subprocess.SubprocessError):
                pass
    return None


def engine_label() -> str:
    return f"{engine_version()} (commit {build_commit(source=True) or 'unknown'})"

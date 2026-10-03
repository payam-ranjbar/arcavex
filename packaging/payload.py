"""Stage identical build identity and skill files for wheels and frozen executables.

Only stdlib imports: Hatch's isolated build must not import the rendering stack.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path


def stage_payload(root: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    try:
        if not (root / ".git").exists():
            raise FileNotFoundError("not a source checkout")
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).strip()
        commit += "-dirty" if dirty else ""
    except (OSError, subprocess.SubprocessError):
        # A source distribution retains the identity captured when it was built.
        saved = root / "build-identity.json"
        commit = (
            json.loads(saved.read_text(encoding="utf-8")).get("commit") if saved.exists() else None
        )
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    (target / "build.json").write_text(
        json.dumps({"version": version, "commit": commit}, indent=2) + "\n", encoding="utf-8"
    )
    skill = target / "skill"
    shutil.copytree(root / "skills" / "arcavex-design-studio", skill, dirs_exist_ok=True)
    marker = skill / "SKILL.md"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            "<!-- engine-build -->", f"Engine build: `{version} (commit {commit or 'unknown'})`."
        ),
        encoding="utf-8",
        newline="\n",
    )
    return target

"""Release-pipeline guards: the properties of CI that fail silently when they regress.

A moved tag, a job that quietly gained write access, or a release manifest that has drifted from
its config does not break a build — it changes what the build trusts or is allowed to do, and
nothing goes red. These checks are cheap and they run with the ordinary unit suite.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# owner/repo@<40 hex>, optionally with a path segment for an action in a subdirectory.
_PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")


def _workflows() -> list[Path]:
    return sorted(_WORKFLOW_DIR.glob("*.yml"))


def _load(path: Path) -> dict[str, Any]:
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for job in workflow.get("jobs", {}).values():
        steps.extend(job.get("steps", []) or [])
    return steps


def test_there_are_workflows_to_check() -> None:
    """Guard the guard: a bad glob would make every assertion below vacuously true."""
    assert _workflows(), f"no workflows found under {_WORKFLOW_DIR}"


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit(path: Path) -> None:
    """A tag can be moved to point at different code; these jobs handle a signing key.

    Local reusable workflows are referenced by path and are pinned by the commit being built.
    """
    unpinned = [
        step["uses"]
        for step in _steps(_load(path))
        if "uses" in step and not step["uses"].startswith("./") and not _PINNED.match(step["uses"])
    ]
    assert not unpinned, f"{path.name} uses unpinned actions: {unpinned}"


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_every_action_records_the_version_it_pins(path: Path) -> None:
    """A bare 40-character hash is unreviewable; the trailing comment says what it was."""
    body = path.read_text(encoding="utf-8")
    missing = [
        line.strip()
        for line in body.splitlines()
        if re.search(r"uses:\s+[\w.-]+/[\w.-]+", line) and "@" in line and "#" not in line
    ]
    assert not missing, f"{path.name} pins without naming a version: {missing}"


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_every_workflow_declares_top_level_permissions(path: Path) -> None:
    """Without an explicit block a job inherits the repository default, which may be write-all."""
    assert "permissions" in _load(path), f"{path.name} does not declare permissions"


def test_only_release_workflows_can_write() -> None:
    """Publishing rights belong to the release lanes; nothing in CI should be able to write."""
    ci = _load(_WORKFLOW_DIR / "ci.yml")
    assert ci["permissions"] == {"contents": "read"}
    for job in ci.get("jobs", {}).values():
        assert "permissions" not in job or job["permissions"] == {"contents": "read"}


def test_release_please_config_and_manifest_agree() -> None:
    """A package missing from the manifest is never released, with no error anywhere."""
    import json

    config = json.loads((_REPO_ROOT / ".github/release-please-config.json").read_text("utf-8"))
    manifest = json.loads((_REPO_ROOT / ".release-please-manifest.json").read_text("utf-8"))
    assert set(config["packages"]) == set(manifest)

    # Independent tags are the whole point of two components; a shared `v*` tag space would make
    # an engine release and a desktop release collide.
    assert config["include-component-in-tag"] is True
    components = {package["component"] for package in config["packages"].values()}
    assert components == {"engine", "desktop"}


def test_manifest_versions_match_the_packages_they_track() -> None:
    """Release Please computes the next version from these, so a stale entry re-releases."""
    import json

    manifest = json.loads((_REPO_ROOT / ".release-please-manifest.json").read_text("utf-8"))

    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    engine_version = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert engine_version and manifest["."] == engine_version.group(1)

    package_json = json.loads((_REPO_ROOT / "apps/desktop/package.json").read_text("utf-8"))
    assert manifest["apps/desktop"] == package_json["version"]


def test_desktop_toolchains_are_pinned_to_exact_versions() -> None:
    """`stable` or a bare major would make two release builds use different compilers."""
    node = (_REPO_ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", node), f"Node pin is not exact: {node!r}"

    rust = (_REPO_ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")
    channel = re.search(r'channel\s*=\s*"([^"]+)"', rust)
    assert channel and re.fullmatch(r"\d+\.\d+\.\d+", channel.group(1)), (
        f"Rust pin is not exact: {channel.group(1) if channel else None!r}"
    )

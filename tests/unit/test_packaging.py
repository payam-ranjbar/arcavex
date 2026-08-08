"""Packaging guards: every declared dependency must be bounded on both sides.

An unbounded requirement lets two installs from the same `pyproject.toml` resolve to different
versions. `mcp` did: an unbounded spec resolved to 2.0.0, which had removed the module
`clients/mcp_server.py` imports, and the suite could not be collected.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

# A requirement string may carry an extras bracket and environment markers; we only care about
# the version specifier set, which is everything after the name/extras and before any marker.
_REQ_RE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(?P<spec>[^;]*)")


def _declared_requirements() -> dict[str, list[str]]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    groups: dict[str, list[str]] = {"dependencies": list(data["project"]["dependencies"])}
    for extra, reqs in data["project"].get("optional-dependencies", {}).items():
        groups[f"optional-dependencies.{extra}"] = list(reqs)
    return groups


def _upper_bounded(spec: str) -> bool:
    """True if the specifier set can never resolve to an unreleased major.

    `<`, `<=`, `==` and `~=` all cap the resolution; a bare name, a lone `>=`, or `!=` alone
    does not.
    """
    return any(op in spec for op in ("<", "==", "~="))


def test_every_dependency_has_an_upper_bound() -> None:
    unbounded: list[str] = []
    for group, reqs in _declared_requirements().items():
        for req in reqs:
            match = _REQ_RE.match(req.strip())
            assert match is not None, f"unparsable requirement {req!r} in {group}"
            if not _upper_bounded(match.group("spec")):
                unbounded.append(f"{group}: {req}")
    assert not unbounded, (
        "Dependencies without an upper bound can resolve to an untested major on a fresh "
        "install: " + ", ".join(unbounded)
    )


def test_every_dependency_has_a_lower_bound() -> None:
    """A cap alone still lets a resolver pick an ancient version that lacks the APIs used."""
    unfloored: list[str] = []
    for group, reqs in _declared_requirements().items():
        for req in reqs:
            match = _REQ_RE.match(req.strip())
            assert match is not None
            spec = match.group("spec")
            if not any(op in spec for op in (">=", "==", "~=")):
                unfloored.append(f"{group}: {req}")
    assert not unfloored, "Dependencies without a lower bound: " + ", ".join(unfloored)


def test_mcp_excludes_the_major_that_removed_fastmcp() -> None:
    """`mcp` 2.0.0 removed `mcp.server.fastmcp`, which `clients.mcp_server` imports."""
    dev = _declared_requirements()["optional-dependencies.dev"]
    spec = next(r for r in dev if r.startswith("mcp"))
    assert "<2" in spec.replace(" ", ""), f"mcp must be capped below 2.0: {spec!r}"


def _load_frozen_verifier() -> ModuleType:
    source = _REPO_ROOT / "packaging" / "verify_frozen.py"
    spec = importlib.util.spec_from_file_location("arcavex_verify_frozen_test", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_verifier_renders_the_current_bilingual_fixture(tmp_path: Path) -> None:
    """The frozen verifier must use a fixture retained by the current repository."""
    verifier = _load_frozen_verifier()
    output = tmp_path / "bilingual.a4.fa.png"

    verifier._render(  # type: ignore[attr-defined]
        [sys.executable, "-m", "arcavex.clients.cli"], "a4", "fa", output
    )

    assert output.is_file()
    assert output.stat().st_size > 0

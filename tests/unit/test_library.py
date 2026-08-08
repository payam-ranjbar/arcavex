"""Library tests: publish, version immutability, default alias, and resolution (spec §5.1/§5.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.library import Library, _version_key

REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO = REPO_ROOT / "tests" / "fixtures" / "basic-poster"


def test_publish_and_resolve_pinned(tmp_path: Path) -> None:
    lib = Library(tmp_path / "templates")
    resolved = lib.publish(HELLO, "poster", "1.0.0")
    assert resolved.path.is_dir() and (resolved.path / "template.yaml").is_file()
    assert lib.resolve("poster@1.0.0").version == "1.0.0"


def test_publish_is_immutable(tmp_path: Path) -> None:
    lib = Library(tmp_path / "templates")
    lib.publish(HELLO, "poster", "1.0.0")
    with pytest.raises(DiagnosticError) as exc:
        lib.publish(HELLO, "poster", "1.0.0")
    assert exc.value.diagnostics[0].code == "ARC-LIB-002"


def test_default_alias_and_bare_name(tmp_path: Path) -> None:
    lib = Library(tmp_path / "templates")
    lib.publish(HELLO, "poster", "1.0.0")
    lib.publish(HELLO, "poster", "1.2.0")  # publishing sets the default to the new version
    assert lib.resolve("poster").version == "1.2.0"
    lib.set_default("poster", "1.0.0")
    assert lib.resolve("poster").version == "1.0.0"


def test_bare_name_without_default_is_ambiguous(tmp_path: Path) -> None:
    lib = Library(tmp_path / "templates")
    lib.publish(HELLO, "poster", "1.0.0", set_default=False)
    with pytest.raises(DiagnosticError) as exc:
        lib.resolve("poster")
    assert exc.value.diagnostics[0].code == "ARC-LIB-003"


def test_unknown_template_and_version(tmp_path: Path) -> None:
    lib = Library(tmp_path / "templates")
    with pytest.raises(DiagnosticError) as exc:
        lib.resolve("nope@1.0.0")
    assert exc.value.diagnostics[0].code == "ARC-LIB-001"
    lib.publish(HELLO, "poster", "1.0.0")
    with pytest.raises(DiagnosticError) as exc2:
        lib.resolve("poster@9.9.9")
    assert exc2.value.diagnostics[0].code == "ARC-LIB-001"


def test_invalid_version_string(tmp_path: Path) -> None:
    lib = Library(tmp_path / "templates")
    with pytest.raises(DiagnosticError) as exc:
        lib.publish(HELLO, "poster", "not-a-version")
    assert exc.value.diagnostics[0].code == "ARC-LIB-004"


def test_version_ordering() -> None:
    versions = ["1.10.0", "1.2.0", "1.2.0-dev", "1.2.1", "0.9.0"]
    ordered = sorted(versions, key=_version_key)
    assert ordered == ["0.9.0", "1.2.0-dev", "1.2.0", "1.2.1", "1.10.0"]

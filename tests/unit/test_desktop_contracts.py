"""Desktop engine handshake contract tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import (
    DoctorCheck,
    DoctorReport,
    EngineHandshakeReport,
    EngineIdentity,
    EnginePaths,
    Facade,
)
from arcavex.kernel.registry import Registries
from arcavex.services.desktop import DesktopService


def _report() -> EngineHandshakeReport:
    doctor = DoctorReport(
        ok=True,
        engine_version="0.1.0",
        checks=[DoctorCheck(name="python", status="ok", detail="Python 3.12.13")],
    )
    return EngineHandshakeReport(
        ok=True,
        identity=EngineIdentity(
            engine_version="0.1.0",
            build_commit="0123456789abcdef",
            artifact_path="C:/Arcavex/arcavex.exe",
            artifact_sha256="a" * 64,
        ),
        mcp_contract_version="2025-06-18",
        accepted_ir_versions=["1.0"],
        produced_ir_version="1.0",
        extension_sdk_version="1.0",
        capabilities=["desktop.engine-handshake", "render.preview"],
        paths=EnginePaths(
            home="C:/Arcavex/home",
            assets="C:/Arcavex/home/assets",
            cache="C:/Arcavex/home/cache",
            extensions="C:/Arcavex/home/extensions",
            fonts="C:/Arcavex/home/fonts",
            styles="C:/Arcavex/home/styles",
            templates="C:/Arcavex/home/templates",
        ),
        doctor=doctor,
    )


def test_engine_handshake_report_carries_the_versioned_desktop_contract() -> None:
    """Dropping any startup compatibility field must break the serialized contract."""
    payload = _report().model_dump(mode="json")

    assert payload == {
        "response_version": 1,
        "ok": True,
        "identity": {
            "engine_version": "0.1.0",
            "build_commit": "0123456789abcdef",
            "artifact_path": "C:/Arcavex/arcavex.exe",
            "artifact_sha256": "a" * 64,
        },
        "mcp_contract_version": "2025-06-18",
        "accepted_ir_versions": ["1.0"],
        "produced_ir_version": "1.0",
        "extension_sdk_version": "1.0",
        "capabilities": ["desktop.engine-handshake", "render.preview"],
        "paths": {
            "home": "C:/Arcavex/home",
            "assets": "C:/Arcavex/home/assets",
            "cache": "C:/Arcavex/home/cache",
            "extensions": "C:/Arcavex/home/extensions",
            "fonts": "C:/Arcavex/home/fonts",
            "styles": "C:/Arcavex/home/styles",
            "templates": "C:/Arcavex/home/templates",
        },
        "doctor": {
            "response_version": 1,
            "ok": True,
            "engine_version": "0.1.0",
            "checks": [{
                "name": "python",
                "status": "ok",
                "detail": "Python 3.12.13",
                "hint": None,
            }],
        },
        "diagnostics": [],
    }


def test_engine_handshake_models_are_frozen() -> None:
    """Desktop clients must receive immutable snapshots, not mutable service state."""
    with pytest.raises(ValidationError):
        _report().identity.engine_version = "9.9.9"


def test_facade_delegates_handshake_to_optional_desktop_service() -> None:
    """Facade injection keeps clients thin while preserving old fake construction."""
    expected = _report()

    class DesktopFake:
        def handshake(self) -> EngineHandshakeReport:
            return expected

    facade = Facade(
        Registries(),
        cast(Any, object()),
        cast(Any, lambda request: None),
        desktop=DesktopFake(),
    )

    assert facade.engine_handshake() is expected


def test_facade_converts_desktop_service_failure_to_a_versioned_report() -> None:
    """A startup probe failure must remain structured instead of escaping to clients."""
    doctor = DoctorReport(ok=True, engine_version="0.1.0", checks=[])

    class BrokenDesktop:
        def handshake(self) -> EngineHandshakeReport:
            raise RuntimeError("identity read failed")

    facade = Facade(
        Registries(),
        cast(Any, object()),
        cast(Any, lambda request: None),
        doctor_probe=lambda: doctor,
        desktop=BrokenDesktop(),
    )

    report = facade.engine_handshake()

    assert not report.ok
    assert report.identity.engine_version == "0.1.0"
    assert [(d.code, d.severity) for d in report.diagnostics] == [("ARC-INT-999", "error")]
    assert "identity read failed" in report.diagnostics[0].hint


def test_desktop_service_reports_proven_release_identity_and_store_paths(
    arcavex_home: Path, tmp_path: Path,
) -> None:
    """A supplied executable is hashed and every persistent home store is explicit."""
    artifact = tmp_path / "arcavex.exe"
    artifact.write_bytes(b"arcavex artifact")
    doctor = DoctorReport(
        ok=True,
        engine_version="0.1.0",
        checks=[DoctorCheck(name="python", status="ok", detail="Python 3.12.13")],
    )
    service = DesktopService(
        engine_version="0.1.0",
        ir_version="1.0",
        extension_sdk_version="1.0",
        doctor_probe=lambda: doctor,
        build_commit="0123456789abcdef",
        artifact_path=artifact,
        capabilities=("render.preview", "desktop.engine-handshake"),
    )

    report = service.handshake()

    assert report.ok
    assert report.identity == EngineIdentity(
        engine_version="0.1.0",
        build_commit="0123456789abcdef",
        artifact_path=str(artifact.resolve()),
        artifact_sha256="5c2518472466989b0ba5578e1459604e56d0957e5aec5a2eea4d45b2e3fb3ce9",
    )
    home = str(arcavex_home.resolve())
    assert report.paths == EnginePaths(
        home=home,
        assets=str(arcavex_home.resolve() / "assets"),
        cache=str(arcavex_home.resolve() / "cache"),
        extensions=str(arcavex_home.resolve() / "extensions"),
        fonts=str(arcavex_home.resolve() / "fonts"),
        styles=str(arcavex_home.resolve() / "styles"),
        templates=str(arcavex_home.resolve() / "templates"),
    )
    assert report.mcp_contract_version == "2025-06-18"
    assert report.accepted_ir_versions == ["1.0"]
    assert report.produced_ir_version == "1.0"
    assert report.extension_sdk_version == "1.0"
    assert report.capabilities == ["desktop.engine-handshake", "render.preview"]
    assert report.doctor is doctor
    assert report.diagnostics == []


def test_interpreted_desktop_service_never_fabricates_release_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dev process reports unknown commit/artifact identity with structured diagnostics."""
    monkeypatch.delenv("ARCAVEX_BUILD_COMMIT", raising=False)
    doctor = DoctorReport(ok=True, engine_version="0.1.0", checks=[])
    report = DesktopService(
        engine_version="0.1.0",
        ir_version="1.0",
        extension_sdk_version="1.0",
        doctor_probe=lambda: doctor,
    ).handshake()

    assert report.identity.build_commit is None
    assert report.identity.artifact_path is None
    assert report.identity.artifact_sha256 is None
    assert [(d.code, d.severity) for d in report.diagnostics] == [
        ("ARC-INT-010", "info"),
        ("ARC-INT-011", "info"),
    ]


def test_bootstrap_wires_live_engine_versions_home_and_doctor(arcavex_home: Path) -> None:
    """Production composition must use the engine's existing version sources verbatim."""
    report = build_facade().engine_handshake()

    assert report.identity.engine_version == report.doctor.engine_version
    assert report.identity.engine_version
    assert report.mcp_contract_version == "2025-06-18"
    assert report.response_version == 1
    assert report.accepted_ir_versions == ["1.0"]
    assert report.produced_ir_version == "1.0"
    assert report.extension_sdk_version == "1.0"
    assert report.capabilities == sorted(report.capabilities)
    assert report.paths.home == str(arcavex_home.resolve())
    assert {check.name for check in report.doctor.checks} == {
        "python", "skia", "icu", "fonts", "exporters", "cache", "temp_dir", "paths", "config"
    }


def test_desktop_handshake_cli_serializes_the_same_facade_model(arcavex_home: Path) -> None:
    """The exact desktop command must remain parse-and-present over the shared model."""
    expected = build_facade().engine_handshake().model_dump(mode="json")

    proc = subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", "desktop", "handshake", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=Path(__file__).resolve().parents[2],
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == expected


def test_schema_export_is_byte_deterministic_and_matches_the_frozen_model() -> None:
    """Two root-level exports must produce canonical UTF-8 JSON with a trailing newline."""
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "export_desktop_schemas.py"
    schema_path = root / "schemas" / "desktop" / "engine-handshake.schema.json"

    first_run = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
        check=False,
    )
    assert first_run.returncode == 0, first_run.stderr
    first = schema_path.read_bytes()

    second_run = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
        check=False,
    )
    assert second_run.returncode == 0, second_run.stderr
    second = schema_path.read_bytes()

    expected = (
        json.dumps(
            EngineHandshakeReport.model_json_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    assert first == second == expected
    assert first.endswith(b"\n")

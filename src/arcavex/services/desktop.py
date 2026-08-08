"""Desktop startup identity and compatibility handshake.

Release identity is deliberately conservative. A frozen process can prove which executable is
running and hash those bytes; an interpreted process cannot claim that the Python interpreter is
the Arcavex release artifact. Likewise, a source commit is reported only when build metadata was
provided explicitly. Unknown identity stays ``None`` and is explained by structured diagnostics.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from arcavex.kernel.api import (
    DoctorReport,
    EngineHandshakeReport,
    EngineIdentity,
    EnginePaths,
)
from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.services.fsutil import home_dir, sha256_file

MCP_CONTRACT_VERSION = "2025-06-18"

DESKTOP_CAPABILITIES: tuple[str, ...] = (
    "desktop.engine-handshake",
    "project.snapshot",
    "render.preview",
)


class DesktopService:
    """Build the frozen startup report consumed by desktop clients."""

    def __init__(
        self,
        *,
        engine_version: str,
        ir_version: str,
        extension_sdk_version: str,
        doctor_probe: Callable[[], DoctorReport],
        build_commit: str | None = None,
        artifact_path: Path | None = None,
        capabilities: Iterable[str] = DESKTOP_CAPABILITIES,
    ) -> None:
        self._engine_version = engine_version
        self._ir_version = ir_version
        self._extension_sdk_version = extension_sdk_version
        self._doctor_probe = doctor_probe
        self._build_commit = build_commit or os.environ.get("ARCAVEX_BUILD_COMMIT")
        self._artifact_path = artifact_path if artifact_path is not None else _frozen_artifact()
        self._capabilities = sorted(set(capabilities))

    def handshake(self) -> EngineHandshakeReport:
        """Return one immutable report with identity, contracts, paths, and doctor data."""
        doctor = self._doctor_probe()
        identity, diagnostics = self._identity()
        home = home_dir().resolve()
        return EngineHandshakeReport(
            ok=doctor.ok,
            identity=identity,
            mcp_contract_version=MCP_CONTRACT_VERSION,
            accepted_ir_versions=[self._ir_version],
            produced_ir_version=self._ir_version,
            extension_sdk_version=self._extension_sdk_version,
            capabilities=list(self._capabilities),
            paths=EnginePaths(
                home=str(home),
                assets=str(home / "assets"),
                cache=str(home / "cache"),
                extensions=str(home / "extensions"),
                fonts=str(home / "fonts"),
                styles=str(home / "styles"),
                templates=str(home / "templates"),
            ),
            doctor=doctor,
            diagnostics=diagnostics,
        )

    def _identity(self) -> tuple[EngineIdentity, list[Diagnostic]]:
        diagnostics: list[Diagnostic] = []
        if self._build_commit is None:
            diagnostics.append(
                diagnostic(
                    "ARC-INT-010",
                    "Build commit is unavailable in this runtime",
                    severity="info",
                    hint="Release builds should provide ARCAVEX_BUILD_COMMIT at build time.",
                )
            )

        artifact_path: str | None = None
        artifact_sha256: str | None = None
        if self._artifact_path is None:
            diagnostics.append(
                diagnostic(
                    "ARC-INT-011",
                    "Executable artifact identity is unavailable in interpreted mode",
                    severity="info",
                    hint="Use the frozen Arcavex executable to obtain a release artifact hash.",
                )
            )
        else:
            resolved = self._artifact_path.resolve()
            artifact_path = str(resolved)
            try:
                artifact_sha256 = sha256_file(resolved)
            except OSError as exc:
                diagnostics.append(
                    diagnostic(
                        "ARC-INT-012",
                        "Executable artifact could not be hashed",
                        severity="warning",
                        file=str(resolved),
                        hint=f"Ensure the executable remains readable. Detail: {exc!r}",
                    )
                )

        return (
            EngineIdentity(
                engine_version=self._engine_version,
                build_commit=self._build_commit,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
            ),
            diagnostics,
        )


def _frozen_artifact() -> Path | None:
    """Return the running Arcavex executable only when PyInstaller proves frozen mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None

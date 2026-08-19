"""The staged desktop sidecar is the engine the desktop will actually supervise.

`packaging/verify_frozen.py` proves the frozen engine renders byte-identically to the dev install.
This module tests the next link in the chain: the copy staged into the desktop bundle by
`scripts/stage_engine_sidecar.ps1`, driven the way `src-tauri/src/engine` drives it — newline
framed JSON-RPC over stdio — rather than through the CLI surface a human uses.

That distinction matters because the desktop trusts three things about the staged artifact that no
other test covers: its SHA-256 equals the pin the supervisor enforces before launch, its MCP
protocol and IR versions equal the ones the lock declares, and the desktop-facing tools respond
over a real stdio session. Any of those can drift while every CLI test still passes.

The whole module skips when nothing is staged, so a contributor who has never built the sidecar is
not blocked; CI's packaging job stages first and therefore runs it.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BINARIES = _REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
_LOCK_PATH = _BINARIES / "engine-lock.json"
_STAGED_EXE = _BINARIES / "engine" / "arcavex.exe"
_TARGET_TRIPLE = "x86_64-pc-windows-msvc"
_FIXTURE_TEMPLATE = _REPO_ROOT / "tests" / "fixtures" / "bilingual-poster" / "template.yaml"

pytestmark = [
    pytest.mark.skipif(
        not _STAGED_EXE.is_file(),
        reason="no staged sidecar; run scripts/stage_engine_sidecar.ps1 -Source Build -UpdateLock",
    ),
    pytest.mark.skipif(sys.platform != "win32", reason="the staged sidecar is a Windows build"),
]


def _lock() -> dict[str, Any]:
    return json.loads(_LOCK_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the staged engine with explicit UTF-8 decoding.

    Windows would otherwise decode with the console codepage, and the engine emits box-drawing
    characters and Farsi text that cp1252 cannot represent.
    """
    return subprocess.run(
        [str(_STAGED_EXE), *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class _McpSession:
    """One newline-framed JSON-RPC stdio session, the transport the supervisor speaks."""

    def __init__(self, arcavex_home: Path) -> None:
        env = {"ARCAVEX_HOME": str(arcavex_home), "PYTHONIOENCODING": "utf-8"}
        self._process = subprocess.Popen(
            [str(_STAGED_EXE), "mcp", "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, **env},
            bufsize=1,
        )
        self._next_id = 0

    def __enter__(self) -> _McpSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=20)
            except subprocess.TimeoutExpired:  # pragma: no cover - only on a wedged engine
                self._process.kill()

    def _send(self, message: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def _read_response(self, request_id: int) -> dict[str, Any]:
        """Read frames until the matching response arrives, skipping notifications."""
        assert self._process.stdout is not None
        while True:
            line = self._process.stdout.readline()
            if not line:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise AssertionError(
                    f"engine closed stdout before answering {request_id}: {stderr}"
                )
            frame = json.loads(line)
            if frame.get("id") == request_id:
                return frame

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        )
        return self._read_response(request_id)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self, protocol_version: str) -> dict[str, Any]:
        response = self.request(
            "initialize",
            {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "arcavex-desktop-test", "version": "0"},
            },
        )
        self.notify("notifications/initialized")
        return response

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        assert "error" not in response, f"{name} failed: {response['error']}"
        result = response["result"]
        assert not result.get("isError"), f"{name} reported a tool error: {result}"
        return json.loads(result["content"][0]["text"])


@pytest.fixture(scope="module")
def handshake() -> dict[str, Any]:
    result = _run(["desktop", "handshake", "--json"])
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_staged_artifact_matches_the_pinned_digest() -> None:
    """The supervisor refuses to launch an engine whose digest differs from the lock.

    A stale staged copy is the failure this catches: the tree still holds an engine, every other
    test passes, and the packaged desktop reports an untrusted artifact at first launch.
    """
    artifact = _lock()["artifacts"].get(_TARGET_TRIPLE)
    assert artifact, "the lock pins no artifact for this platform; restage with -UpdateLock"
    assert _sha256(_STAGED_EXE) == artifact["sha256"]


def test_pinned_install_path_is_relative_to_the_desktop_executable() -> None:
    """`EngineSpec::resolve` joins this onto the directory of the running desktop executable."""
    artifact = _lock()["artifacts"][_TARGET_TRIPLE]
    file = artifact["file"]
    assert not Path(file).is_absolute(), f"{file} would not resolve inside an installation"
    assert file.endswith("arcavex.exe")
    assert "\\" not in file, "use forward slashes so the manifest is platform-neutral"


def test_staged_engine_reports_the_pinned_contract_versions(handshake: dict[str, Any]) -> None:
    lock = _lock()
    assert handshake["ok"] is True
    assert handshake["identity"]["engine_version"] == lock["engine_version"]
    assert handshake["mcp_contract_version"] == lock["mcp_contract_version"]
    assert handshake["produced_ir_version"] == lock["produced_ir_version"]
    assert handshake["accepted_ir_versions"] == lock["accepted_ir_versions"]


def test_staged_engine_self_reports_its_own_digest(handshake: dict[str, Any]) -> None:
    """About and support surfaces show this value, so it must describe the running artifact."""
    assert handshake["identity"]["artifact_sha256"] == _sha256(_STAGED_EXE)
    assert Path(handshake["identity"]["artifact_path"]) == _STAGED_EXE


def test_sidecar_completes_the_mcp_stdio_handshake(tmp_path: Path) -> None:
    """The desktop's first act is this exchange; if it fails the app has no engine at all."""
    lock = _lock()
    with _McpSession(tmp_path / "home") as session:
        response = session.initialize(lock["mcp_contract_version"])
        assert "error" not in response, response
        assert response["result"]["protocolVersion"] == lock["mcp_contract_version"]

        tools = session.request("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        # The tools the Phase 1 viewer cannot open a project without.
        required = {
            "engine_handshake",
            "project_snapshot",
            "project_validate",
            "project_preview",
            "layer_tree",
            "hit_test",
        }
        assert required <= names, f"staged sidecar is missing {sorted(required - names)}"


def test_sidecar_opens_a_project_and_renders_a_preview(tmp_path: Path) -> None:
    """The packaged viewer's whole loop, driven through the staged artifact only.

    Nothing here touches the repository's Python: the project is scaffolded by the frozen
    executable and rendered by the frozen executable, which is what a machine with no Python
    installed will do.
    """
    project = tmp_path / "poster"
    home = tmp_path / "home"
    created = _run(
        ["project", "new", str(project), "--template", str(_FIXTURE_TEMPLATE), "--json"],
        cwd=tmp_path,
    )
    assert created.returncode == 0, created.stderr

    with _McpSession(home) as session:
        session.initialize(_lock()["mcp_contract_version"])

        snapshot = session.call_tool("project_snapshot", {"project": str(project)})
        assert snapshot["ok"] is True
        assert snapshot["project_revision"] and snapshot["render_revision"]

        preview = session.call_tool("project_preview", {"project": str(project)})
        assert preview["ok"] is True, preview.get("diagnostics")
        assert preview["previews"], "a scaffolded project must declare at least one target"
        rendered = Path(preview["previews"][0]["output_path"])
        assert rendered.is_file() and rendered.stat().st_size > 0

        layers = session.call_tool("layer_tree", {"project": str(project), "mode": "authored"})
        assert layers["ok"] is True
        assert layers["root"], "the viewer's Layers panel needs a root node"


def test_sidecar_does_not_rewrite_the_project_it_opens(tmp_path: Path) -> None:
    """Viewing must not mutate source — the invariant the whole open-in-place model rests on."""
    project = tmp_path / "poster"
    created = _run(
        ["project", "new", str(project), "--template", str(_FIXTURE_TEMPLATE), "--json"],
        cwd=tmp_path,
    )
    assert created.returncode == 0, created.stderr

    before = {
        path.relative_to(project).as_posix(): _sha256(path)
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }

    with _McpSession(tmp_path / "home") as session:
        session.initialize(_lock()["mcp_contract_version"])
        session.call_tool("project_snapshot", {"project": str(project)})
        session.call_tool("layer_tree", {"project": str(project), "mode": "authored"})

    after = {
        path.relative_to(project).as_posix(): _sha256(path)
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }
    assert before == after

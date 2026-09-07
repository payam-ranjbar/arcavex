"""`arcavex mcp install` end to end, through the Typer app.

Isolated the way the unit tests are: a temp home standing in for the real one, %APPDATA% and
~/.codex included, and the host CLIs replaced by a recorder. `claude` is on PATH on a developer
machine, and the real `claude mcp add` would edit that developer's own ~/.claude.json.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from typer.testing import CliRunner

from arcavex.clients.cli import app
from arcavex.services import mcp_hosts

runner = CliRunner()

COMMAND = Path("C:/engine/arcavex.exe") if sys.platform == "win32" else Path("/opt/engine/arcavex")
SERVE = [str(COMMAND), "mcp", "serve"]


@dataclass
class FakeCli:
    """Answers `mcp get` as "not registered" and every other subcommand with success."""

    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str]) -> CompletedProcess[str]:
        self.calls.append(list(argv))
        if argv[2] == "get":
            return CompletedProcess(argv, 1, "", 'No MCP server named "arcavex".')
        return CompletedProcess(argv, 0, "", "")

    def subcommands(self) -> list[str]:
        return [argv[2] for argv in self.calls]


@dataclass
class Hosts:
    home: Path
    found: dict[str, str]
    cli: FakeCli
    desktop_config: Path
    codex_config: Path


@pytest.fixture()
def hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Hosts:
    """A machine with no AI host on it; a test adds the ones it needs."""
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    found: dict[str, str] = {}
    cli = FakeCli()
    monkeypatch.setattr(mcp_hosts, "_default_which", found.get)
    monkeypatch.setattr(mcp_hosts, "_default_runner", cli)
    if sys.platform == "win32":
        desktop = home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
        desktop = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
    return Hosts(home, found, cli, desktop, home / ".codex" / "config.toml")


def test_list_shows_each_host_its_location_and_state(hosts: Hosts) -> None:
    hosts.desktop_config.parent.mkdir(parents=True)

    result = runner.invoke(app, ["mcp", "install", "--list", "--no-color"])

    assert result.exit_code == 0, result.output
    assert "Claude Code" in result.output and "host not found" in result.output
    assert "Claude Desktop" in result.output and "not registered" in result.output
    assert "Codex CLI" in result.output
    assert "command:" in result.output and "mcp serve" in result.output
    assert not hosts.desktop_config.exists(), "--list wrote a file"


def test_print_writes_nothing_and_shows_a_snippet_per_host(hosts: Hosts) -> None:
    hosts.desktop_config.parent.mkdir(parents=True)
    hosts.codex_config.parent.mkdir()

    result = runner.invoke(app, ["mcp", "install", "--print", "--no-color"])

    assert result.exit_code == 0, result.output
    assert "claude mcp add -s user arcavex --" in result.output
    assert '"mcpServers"' in result.output
    assert "[mcp_servers.arcavex]" in result.output
    assert not hosts.desktop_config.exists() and not hosts.codex_config.exists()
    assert hosts.cli.calls == []


def test_json_reports_the_command_and_every_target(hosts: Hosts) -> None:
    result = runner.invoke(app, ["mcp", "install", "--list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["response_version"] == 1 and payload["ok"] is True
    assert [t["key"] for t in payload["targets"]] == ["claude-code", "claude-desktop", "codex"]
    assert Path(payload["command"][0]).is_absolute()
    assert payload["command"][-2:] == ["mcp", "serve"]
    assert {"key", "label", "location", "available", "registered", "snippet"} <= set(
        payload["targets"][0]
    )
    assert payload["installed"] == [] and payload["diagnostics"] == []


def test_install_registers_the_hosts_present_and_says_what_to_do_next(hosts: Hosts) -> None:
    hosts.desktop_config.parent.mkdir(parents=True)
    hosts.found["claude"] = "claude"

    result = runner.invoke(app, ["mcp", "install", "--no-color", "--command", str(COMMAND)])

    assert result.exit_code == 0, result.output
    data = json.loads(hosts.desktop_config.read_text(encoding="utf-8"))
    assert data["mcpServers"]["arcavex"] == {"command": str(COMMAND), "args": ["mcp", "serve"]}
    assert hosts.cli.subcommands() == ["get", "add"]
    assert hosts.cli.calls[1][2:] == ["add", "-s", "user", "arcavex", "--", *SERVE]
    assert "Registered the Arcavex MCP server with 2 host(s)" in result.output
    assert "open a new Claude Code session" in result.output
    assert "reopen Claude Desktop" in result.output
    # Codex is absent: a notice, not a failure.
    assert "INFO ARC-MCP-002" in result.output
    assert not hosts.codex_config.exists()


def test_install_json_names_what_was_written(hosts: Hosts) -> None:
    hosts.desktop_config.parent.mkdir(parents=True)

    result = runner.invoke(app, ["mcp", "install", "--json", "--command", str(COMMAND)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True and payload["installed"] == ["claude-desktop"]
    assert payload["command"] == [str(COMMAND), "mcp", "serve"]
    by_key = {t["key"]: t for t in payload["targets"]}
    assert by_key["claude-desktop"]["registered"] is True
    assert by_key["claude-code"]["available"] is False
    assert [d["code"] for d in payload["diagnostics"]] == ["ARC-MCP-002", "ARC-MCP-002"]


def test_a_second_run_without_force_warns_and_exits_1(hosts: Hosts) -> None:
    hosts.desktop_config.parent.mkdir(parents=True)
    first = runner.invoke(
        app, ["mcp", "install", "-t", "claude-desktop", "--command", str(COMMAND)]
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        app, ["mcp", "install", "-t", "claude-desktop", "--no-color", "--command", str(COMMAND)]
    )

    assert second.exit_code == 1, second.output
    assert "WARNING ARC-MCP-003" in second.output and "--force" in second.output

    forced = runner.invoke(
        app, ["mcp", "install", "-t", "desktop", "--force", "--command", str(COMMAND)]
    )
    assert forced.exit_code == 0, forced.output


def test_an_absent_host_named_explicitly_exits_3_with_the_snippet(hosts: Hosts) -> None:
    result = runner.invoke(
        app, ["mcp", "install", "-t", "codex", "--no-color", "--command", str(COMMAND)]
    )

    assert result.exit_code == 3, result.output
    assert "ERROR ARC-MCP-002" in result.output
    assert "[mcp_servers.arcavex]" in result.output
    assert not hosts.codex_config.exists()


def test_an_unknown_host_exits_1_and_names_the_real_ones(hosts: Hosts) -> None:
    result = runner.invoke(app, ["mcp", "install", "-t", "emacs", "--no-color"])

    assert result.exit_code == 1, result.output
    assert "ARC-MCP-001" in result.output
    assert "claude-desktop" in result.output and "codex" in result.output


def test_quiet_prints_nothing_but_still_registers(hosts: Hosts) -> None:
    hosts.codex_config.parent.mkdir()

    result = runner.invoke(
        app, ["mcp", "install", "-t", "chatgpt", "--quiet", "--command", str(COMMAND)]
    )

    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""
    assert "[mcp_servers.arcavex]" in hosts.codex_config.read_text(encoding="utf-8")

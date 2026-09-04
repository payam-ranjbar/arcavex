"""Registering the MCP server with an AI host (`arcavex mcp install`).

Every test runs against an isolated home and a stand-in for the `claude`/`codex` CLIs. The real
ones must never be invoked — `claude` is on PATH on a developer machine, and `claude mcp add`
would edit that developer's own ~/.claude.json — and nothing may touch the real %APPDATA% or
~/.codex. The autouse fixture below enforces both for every test in this module.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from arcavex.bootstrap import build_facade
from arcavex.services import mcp_hosts
from arcavex.services.mcp_hosts import SERVER_NAME, McpHostService, resolve_command

# An engine path that exists nowhere: what matters is that it is registered verbatim.
COMMAND = Path("C:/engine/arcavex.exe") if sys.platform == "win32" else Path("/opt/engine/arcavex")
SERVE = [str(COMMAND), "mcp", "serve"]


def _no_cli(argv: list[str]) -> CompletedProcess[str]:
    raise AssertionError(f"a host CLI was invoked: {argv}")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No test may see the real home, %APPDATA%, ~/.codex, or the real host CLIs."""
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(mcp_hosts, "_default_which", lambda name: None)
    monkeypatch.setattr(mcp_hosts, "_default_runner", _no_cli)
    return home


@dataclass
class FakeCli:
    """Stands in for `claude` and `codex`: records every call, answers from a script."""

    registered: bool = False
    fail: dict[str, str] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str]) -> CompletedProcess[str]:
        self.calls.append(list(argv))
        sub = argv[2]
        if sub in self.fail:
            return CompletedProcess(argv, 1, "", self.fail[sub])
        if sub == "get":
            if self.registered:
                return CompletedProcess(argv, 0, f"{SERVER_NAME}: stdio", "")
            return CompletedProcess(argv, 1, "", f'No MCP server named "{SERVER_NAME}".')
        return CompletedProcess(argv, 0, "", "")

    def subcommands(self) -> list[str]:
        return [argv[2] for argv in self.calls]


def service(
    home: Path,
    *,
    which: Mapping[str, str] | None = None,
    runner: FakeCli | None = None,
    platform: str = "win32",
    environ: Mapping[str, str] | None = None,
) -> McpHostService:
    """A service on a machine with exactly the given CLIs, home, and platform."""
    found = dict(which or {})
    env = {"APPDATA": str(home / "AppData" / "Roaming"), **(environ or {})}
    return McpHostService(
        which=found.get, runner=runner or _no_cli, platform=platform, home=home, environ=env
    )


def desktop_config(home: Path, platform: str = "win32") -> Path:
    if platform == "win32":
        return home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def codex_config(home: Path) -> Path:
    return home / ".codex" / "config.toml"


# --------------------------------------------------------------------------- the command


def test_a_frozen_executable_is_registered_as_itself(tmp_path: Path) -> None:
    exe = tmp_path / "arcavex.exe"
    assert resolve_command(executable=str(exe), frozen=True, windows=True) == [
        str(exe),
        "mcp",
        "serve",
    ]


def test_the_console_script_beside_the_interpreter_wins(tmp_path: Path) -> None:
    """The host should start the engine this command belongs to, not whatever `python` is."""
    (tmp_path / "python.exe").write_bytes(b"")
    (tmp_path / "arcavex.exe").write_bytes(b"")
    command = resolve_command(executable=str(tmp_path / "python.exe"), frozen=False, windows=True)
    assert command == [str(tmp_path / "arcavex.exe"), "mcp", "serve"]


def test_without_a_console_script_the_interpreter_runs_the_module(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    command = resolve_command(executable=str(python), frozen=False, windows=True)
    assert command == [str(python), "-m", "arcavex", "mcp", "serve"]


def test_a_posix_console_script_has_no_extension(tmp_path: Path) -> None:
    (tmp_path / "arcavex").write_bytes(b"")
    command = resolve_command(executable=str(tmp_path / "python"), frozen=False, windows=False)
    assert command[0] == str(tmp_path / "arcavex")


def test_an_override_is_made_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    command = resolve_command(Path("bin/arcavex.exe"))
    assert Path(command[0]).is_absolute()
    assert Path(command[0]) == tmp_path / "bin" / "arcavex.exe"
    assert command[1:] == ["mcp", "serve"]


def test_a_symlinked_interpreter_stays_in_its_venv(tmp_path: Path) -> None:
    """On macOS/Linux a venv's python is a symlink to the base interpreter.

    Following it would register an interpreter that cannot import the engine.
    """
    base = tmp_path / "base" / "python"
    base.parent.mkdir()
    base.write_bytes(b"")
    venv = tmp_path / "venv"
    venv.mkdir()
    try:
        (venv / "python").symlink_to(base)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    (venv / "arcavex").write_bytes(b"")
    command = resolve_command(executable=str(venv / "python"), frozen=False, windows=False)
    assert command[0] == str(venv / "arcavex")


def test_the_default_command_is_absolute_and_serves() -> None:
    command = resolve_command()
    assert Path(command[0]).is_absolute()
    assert command[-2:] == ["mcp", "serve"]


# ------------------------------------------------------------------------ listing, naming


def test_a_bare_machine_has_every_host_absent(isolated_home: Path) -> None:
    report = service(isolated_home).list_targets(command=COMMAND)
    assert report.ok and report.installed == []
    assert [t.key for t in report.targets] == ["claude-code", "claude-desktop", "codex"]
    assert not any(t.available for t in report.targets)
    assert not any(t.registered for t in report.targets)
    assert report.command == SERVE


def test_snippets_are_what_a_person_would_paste(isolated_home: Path) -> None:
    by_key = {t.key: t for t in service(isolated_home).list_targets(command=COMMAND).targets}
    assert by_key["claude-code"].snippet == f"claude mcp add -s user arcavex -- {COMMAND} mcp serve"
    entry = {"command": str(COMMAND), "args": ["mcp", "serve"]}
    assert json.loads(by_key["claude-desktop"].snippet) == {"mcpServers": {"arcavex": entry}}
    assert tomllib.loads(by_key["codex"].snippet) == {"mcp_servers": {"arcavex": entry}}


def test_a_path_with_spaces_is_quoted_for_the_shell(isolated_home: Path) -> None:
    spaced = isolated_home / "Program Files" / "arcavex.exe"
    snippet = service(isolated_home).list_targets(command=spaced).targets[0].snippet
    assert f'"{spaced}"' in snippet


def test_an_unknown_host_names_the_real_ones(isolated_home: Path) -> None:
    report = service(isolated_home).install(targets=["emacs"], command=COMMAND)
    assert not report.ok
    [diag] = report.diagnostics
    assert diag.code == "ARC-MCP-001" and "emacs" in diag.message
    assert diag.hint is not None
    for name in ("claude-code", "claude-desktop", "codex", "desktop", "chatgpt"):
        assert name in diag.hint


@pytest.mark.parametrize(("alias", "key"), [("desktop", "claude-desktop"), ("chatgpt", "codex")])
def test_aliases_resolve_to_one_host(isolated_home: Path, alias: str, key: str) -> None:
    report = service(isolated_home).install(targets=[alias, key], command=COMMAND)
    assert [t.key for t in report.targets] == [key]


def test_the_chatgpt_alias_is_explained(isolated_home: Path) -> None:
    """A person who asked for ChatGPT should learn why they got Codex."""
    codex = service(isolated_home).list_targets(command=COMMAND).targets[2]
    assert codex.note is not None and "ChatGPT" in codex.note


def test_absent_hosts_are_notices_in_a_default_run(isolated_home: Path) -> None:
    """A machine with no assistant on it has done everything it can; that is not a failure."""
    report = service(isolated_home).install(command=COMMAND)
    assert report.ok
    assert report.installed == []
    assert [d.code for d in report.diagnostics] == ["ARC-MCP-002"] * 3
    assert all(d.severity == "info" for d in report.diagnostics)


def test_an_absent_host_asked_for_by_name_is_an_error_with_the_snippet(
    isolated_home: Path,
) -> None:
    report = service(isolated_home).install(targets=["claude-code"], command=COMMAND)
    assert not report.ok
    [diag] = report.diagnostics
    assert diag.code == "ARC-MCP-002" and diag.severity == "error"
    assert diag.hint is not None
    assert f"claude mcp add -s user arcavex -- {COMMAND} mcp serve" in diag.hint


def test_one_success_beside_absent_hosts_is_ok(isolated_home: Path) -> None:
    desktop_config(isolated_home).parent.mkdir(parents=True)
    report = service(isolated_home).install(command=COMMAND)
    assert report.ok and report.installed == ["claude-desktop"]
    assert [d.code for d in report.diagnostics] == ["ARC-MCP-002", "ARC-MCP-002"]
    by_key = {t.key: t for t in report.targets}
    assert by_key["claude-desktop"].registered
    assert not by_key["codex"].available


def test_targets_are_not_under_arcavex_home(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host keeps its configuration in its own directory, not in ARCAVEX_HOME."""
    engine_home = isolated_home / "engine-home"
    monkeypatch.setenv("ARCAVEX_HOME", str(engine_home))
    locations = [t.location for t in service(isolated_home).list_targets(command=COMMAND).targets]
    assert not any(str(engine_home) in location for location in locations), locations


# ------------------------------------------------------------------------------ Claude Code


def test_claude_code_is_registered_through_its_cli_at_user_scope(isolated_home: Path) -> None:
    cli = FakeCli()
    report = service(isolated_home, which={"claude": "C:/npm/claude.cmd"}, runner=cli).install(
        targets=["claude-code"], command=COMMAND
    )
    assert report.ok and report.installed == ["claude-code"]
    assert cli.calls == [
        ["C:/npm/claude.cmd", "mcp", "get", "arcavex"],
        ["C:/npm/claude.cmd", "mcp", "add", "-s", "user", "arcavex", "--", *SERVE],
    ]
    assert report.targets[0].registered


def test_list_asks_claude_whether_it_is_registered(isolated_home: Path) -> None:
    cli = FakeCli(registered=True)
    report = service(isolated_home, which={"claude": "claude"}, runner=cli).list_targets(
        command=COMMAND
    )
    claude = report.targets[0]
    assert claude.available and claude.registered
    assert cli.subcommands() == ["get"]


def test_claude_code_already_registered_is_refused_without_force(isolated_home: Path) -> None:
    cli = FakeCli(registered=True)
    report = service(isolated_home, which={"claude": "claude"}, runner=cli).install(
        targets=["claude-code"], command=COMMAND
    )
    assert not report.ok and report.installed == []
    assert [d.code for d in report.diagnostics] == ["ARC-MCP-003"]
    assert cli.subcommands() == ["get"]


def test_force_removes_the_user_scope_entry_then_adds(isolated_home: Path) -> None:
    cli = FakeCli(registered=True)
    report = service(isolated_home, which={"claude": "claude"}, runner=cli).install(
        targets=["claude-code"], command=COMMAND, force=True
    )
    assert report.ok and report.installed == ["claude-code"]
    assert cli.subcommands() == ["get", "remove", "add"]
    assert cli.calls[1] == ["claude", "mcp", "remove", "-s", "user", "arcavex"]


def test_a_failing_host_cli_is_reported_with_what_it_said(isolated_home: Path) -> None:
    cli = FakeCli(fail={"add": "MCP server arcavex already exists in user config"})
    report = service(isolated_home, which={"claude": "claude"}, runner=cli).install(
        targets=["claude-code"], command=COMMAND
    )
    assert not report.ok and report.installed == []
    [diag] = report.diagnostics
    assert diag.code == "ARC-MCP-004"
    assert "already exists in user config" in diag.message


def test_a_host_cli_that_cannot_run_is_reported_not_raised(isolated_home: Path) -> None:
    def broken(argv: list[str]) -> CompletedProcess[str]:
        raise OSError("cannot spawn")

    report = McpHostService(
        which={"claude": "claude"}.get,
        runner=broken,
        platform="win32",
        home=isolated_home,
        environ={},
    ).install(targets=["claude-code"], command=COMMAND)
    assert not report.ok
    assert report.diagnostics[0].code == "ARC-MCP-004"
    assert "cannot spawn" in report.diagnostics[0].message


# --------------------------------------------------------------------------- Claude Desktop


def test_desktop_is_unavailable_until_the_app_has_a_config_directory(isolated_home: Path) -> None:
    desktop = service(isolated_home).list_targets(command=COMMAND).targets[1]
    assert not desktop.available
    assert desktop.location == str(desktop_config(isolated_home))


def test_desktop_entry_is_added_keeping_every_other_key_and_the_indent(
    isolated_home: Path,
) -> None:
    config = desktop_config(isolated_home)
    config.parent.mkdir(parents=True)
    before = (
        "{\n"
        '    "globalShortcut": "Ctrl+Space",\n'
        '    "mcpServers": {\n'
        '        "other": {\n'
        '            "command": "other-server",\n'
        '            "args": []\n'
        "        }\n"
        "    }\n"
        "}\n"
    )
    config.write_text(before, encoding="utf-8")

    report = service(isolated_home).install(targets=["claude-desktop"], command=COMMAND)

    assert report.ok and report.installed == ["claude-desktop"]
    text = config.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["globalShortcut"] == "Ctrl+Space"
    assert data["mcpServers"]["other"] == {"command": "other-server", "args": []}
    assert data["mcpServers"]["arcavex"] == {"command": str(COMMAND), "args": ["mcp", "serve"]}
    assert '\n    "globalShortcut"' in text, "the file's four-space indent was not kept"
    assert config.with_name(config.name + ".bak").read_text(encoding="utf-8") == before
    # Atomic: the temp file is gone, and nothing but the file and its backup remain.
    assert sorted(p.name for p in config.parent.iterdir()) == [config.name, config.name + ".bak"]


def test_desktop_config_is_created_when_the_app_has_not_written_one(isolated_home: Path) -> None:
    config = desktop_config(isolated_home)
    config.parent.mkdir(parents=True)
    report = service(isolated_home).install(targets=["claude-desktop"], command=COMMAND)
    assert report.ok
    assert json.loads(config.read_text(encoding="utf-8")) == {
        "mcpServers": {"arcavex": {"command": str(COMMAND), "args": ["mcp", "serve"]}}
    }
    assert not config.with_name(config.name + ".bak").exists(), "there was nothing to back up"


def test_desktop_existing_entry_is_refused_without_force_and_replaced_with_it(
    isolated_home: Path,
) -> None:
    config = desktop_config(isolated_home)
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"mcpServers": {"arcavex": {"command": "old.exe", "args": []}}}),
        encoding="utf-8",
    )
    svc = service(isolated_home)

    refused = svc.install(targets=["claude-desktop"], command=COMMAND)
    assert not refused.ok and refused.installed == []
    assert [d.code for d in refused.diagnostics] == ["ARC-MCP-003"]
    assert json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["arcavex"] == {
        "command": "old.exe",
        "args": [],
    }

    forced = svc.install(targets=["claude-desktop"], command=COMMAND, force=True)
    assert forced.ok and forced.installed == ["claude-desktop"]
    assert json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["arcavex"] == {
        "command": str(COMMAND),
        "args": ["mcp", "serve"],
    }


def test_desktop_invalid_json_is_reported_and_left_alone(isolated_home: Path) -> None:
    config = desktop_config(isolated_home)
    config.parent.mkdir(parents=True)
    config.write_text("{ not json", encoding="utf-8")
    report = service(isolated_home).install(targets=["claude-desktop"], command=COMMAND)
    assert not report.ok
    [diag] = report.diagnostics
    assert diag.code == "ARC-MCP-004" and "not valid JSON" in diag.message
    assert config.read_text(encoding="utf-8") == "{ not json"
    assert not config.with_name(config.name + ".bak").exists()


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_desktop_config_lives_where_the_app_puts_it(isolated_home: Path, platform: str) -> None:
    location = service(isolated_home, platform=platform).list_targets(command=COMMAND).targets[1]
    assert Path(location.location) == desktop_config(isolated_home, platform)


def test_linux_honours_xdg_config_home(isolated_home: Path) -> None:
    xdg = isolated_home / "xdg"
    report = service(
        isolated_home, platform="linux", environ={"XDG_CONFIG_HOME": str(xdg)}
    ).list_targets(command=COMMAND)
    assert Path(report.targets[1].location) == xdg / "Claude" / "claude_desktop_config.json"


# ------------------------------------------------------------------------------------ Codex


def test_codex_cli_is_preferred_when_present(isolated_home: Path) -> None:
    cli = FakeCli()
    report = service(isolated_home, which={"codex": "/usr/bin/codex"}, runner=cli).install(
        targets=["codex"], command=COMMAND
    )
    assert report.ok and report.installed == ["codex"]
    assert cli.calls == [["/usr/bin/codex", "mcp", "add", "arcavex", "--", *SERVE]]
    assert not codex_config(isolated_home).exists(), "the CLI owns the file; we do not write it"


def test_codex_force_with_the_cli_removes_then_adds(isolated_home: Path) -> None:
    config = codex_config(isolated_home)
    config.parent.mkdir()
    config.write_text('[mcp_servers.arcavex]\ncommand = "old"\n', encoding="utf-8")
    cli = FakeCli()
    report = service(isolated_home, which={"codex": "codex"}, runner=cli).install(
        targets=["codex"], command=COMMAND, force=True
    )
    assert report.ok
    assert cli.calls == [
        ["codex", "mcp", "remove", "arcavex"],
        ["codex", "mcp", "add", "arcavex", "--", *SERVE],
    ]


def test_codex_without_the_cli_appends_a_table_to_the_existing_config(
    isolated_home: Path,
) -> None:
    config = codex_config(isolated_home)
    config.parent.mkdir()
    before = 'model = "o3"\n\n[mcp_servers.other]\ncommand = "other"\nargs = ["--flag"]\n'
    config.write_text(before, encoding="utf-8")

    report = service(isolated_home).install(targets=["codex"], command=COMMAND)

    assert report.ok and report.installed == ["codex"]
    text = config.read_text(encoding="utf-8")
    assert text.startswith(before), "the existing content was reformatted"
    data = tomllib.loads(text)
    assert data["model"] == "o3"
    assert data["mcp_servers"]["other"] == {"command": "other", "args": ["--flag"]}
    assert data["mcp_servers"]["arcavex"] == {"command": str(COMMAND), "args": ["mcp", "serve"]}
    assert config.with_name("config.toml.bak").read_text(encoding="utf-8") == before


def test_codex_config_is_created_when_only_the_directory_exists(isolated_home: Path) -> None:
    config = codex_config(isolated_home)
    config.parent.mkdir()
    report = service(isolated_home).install(targets=["codex"], command=COMMAND)
    assert report.ok
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert data == {"mcp_servers": {"arcavex": {"command": str(COMMAND), "args": ["mcp", "serve"]}}}
    assert not config.with_name("config.toml.bak").exists()


def test_codex_existing_table_is_refused_without_force(isolated_home: Path) -> None:
    config = codex_config(isolated_home)
    config.parent.mkdir()
    before = '[mcp_servers.arcavex]\ncommand = "old"\nargs = []\n'
    config.write_text(before, encoding="utf-8")
    report = service(isolated_home).install(targets=["codex"], command=COMMAND)
    assert not report.ok and report.installed == []
    assert [d.code for d in report.diagnostics] == ["ARC-MCP-003"]
    assert config.read_text(encoding="utf-8") == before


def test_codex_force_rewrites_only_the_arcavex_table(isolated_home: Path) -> None:
    """Everything around the table — comments, other tables, even its own sub-table — stays."""
    config = codex_config(isolated_home)
    config.parent.mkdir()
    head = '# my config\nmodel = "o3"\n\n'
    tail = '\n[mcp_servers.arcavex.env]\nFOO = "bar"\n\n[mcp_servers.other]\ncommand = "other"\n'
    config.write_text(
        head + '[mcp_servers.arcavex]\ncommand = "old"\nargs = ["x"]\n' + tail, encoding="utf-8"
    )

    report = service(isolated_home).install(targets=["codex"], command=COMMAND, force=True)

    assert report.ok and report.installed == ["codex"]
    text = config.read_text(encoding="utf-8")
    assert text.startswith(head + "[mcp_servers.arcavex]\n")
    assert text.endswith(tail)
    assert 'command = "old"' not in text and '"x"' not in text
    data = tomllib.loads(text)
    assert data["mcp_servers"]["arcavex"] == {
        "command": str(COMMAND),
        "args": ["mcp", "serve"],
        "env": {"FOO": "bar"},
    }
    assert data["mcp_servers"]["other"] == {"command": "other"}


def test_codex_force_refuses_an_entry_it_cannot_rewrite(isolated_home: Path) -> None:
    """An inline table is a real entry tomllib sees but no header to swap; appending would
    duplicate the key and break the file, so nothing is written."""
    config = codex_config(isolated_home)
    config.parent.mkdir()
    before = '[mcp_servers]\narcavex = { command = "old", args = [] }\n'
    config.write_text(before, encoding="utf-8")
    report = service(isolated_home).install(targets=["codex"], command=COMMAND, force=True)
    assert not report.ok
    [diag] = report.diagnostics
    assert diag.code == "ARC-MCP-004"
    assert config.read_text(encoding="utf-8") == before
    assert not config.with_name("config.toml.bak").exists()


def test_codex_invalid_toml_is_reported_and_left_alone(isolated_home: Path) -> None:
    config = codex_config(isolated_home)
    config.parent.mkdir()
    before = "this is = not = toml\n"
    config.write_text(before, encoding="utf-8")
    report = service(isolated_home).install(targets=["codex"], command=COMMAND)
    assert not report.ok
    [diag] = report.diagnostics
    assert diag.code == "ARC-MCP-004" and "not valid TOML" in diag.message
    assert config.read_text(encoding="utf-8") == before


def test_codex_home_can_be_relocated(isolated_home: Path) -> None:
    elsewhere = isolated_home / "elsewhere"
    elsewhere.mkdir()
    report = service(isolated_home, environ={"CODEX_HOME": str(elsewhere)}).install(
        targets=["codex"], command=COMMAND
    )
    assert report.ok and (elsewhere / "config.toml").is_file()


# ----------------------------------------------------------------------------------- facade


def test_facade_exposes_list_and_install(isolated_home: Path) -> None:
    """The CLI reaches this through kernel.api, so the facade must carry it end to end."""
    config = desktop_config(isolated_home, sys.platform)
    config.parent.mkdir(parents=True)
    facade = build_facade()

    listed = facade.list_mcp_targets()
    assert listed.ok
    assert [t.key for t in listed.targets] == ["claude-code", "claude-desktop", "codex"]
    assert not config.exists()

    report = facade.install_mcp(["claude-desktop"], COMMAND)
    assert report.ok, report.diagnostics
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["mcpServers"]["arcavex"] == {"command": str(COMMAND), "args": ["mcp", "serve"]}

"""Register the MCP server with an AI host: Claude Code, Claude Desktop, Codex.

``arcavex skill install`` teaches a host *how* to drive the engine; this registers the engine
itself so the host can reach it at all. Each host keeps its registrations somewhere different —
Claude Code and Codex behind their own CLIs (``claude mcp add``, ``codex mcp add``), Claude Desktop
in a JSON file under the user's application-data directory — and a person who has just installed
the engine should not have to know any of that. One command, every host that is present.

Two rules keep it safe to run on a machine that already has a working setup. A host that owns a
CLI is registered *through* that CLI, never by editing its file: the format is the host's, and it
changes. A file this service does edit is rewritten atomically with every other key preserved, and
a ``.bak`` of the previous content is left beside it.

Where a host is not present nothing is written: the target reports as unavailable, with the exact
snippet a person can paste later, so ``--print`` and the diagnostics are the manual route.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from arcavex.kernel.api import McpInstallReport, McpTargetInfo
from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.services.fsutil import atomic_write_text

#: The name the server is registered under in every host.
SERVER_NAME = "arcavex"

# A host CLI that has not answered in this long is hung, not slow; report rather than wait.
_CLI_TIMEOUT_S = 60

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a host CLI and capture what it said; the caller reads the exit code."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_CLI_TIMEOUT_S,
        check=False,
    )


def _default_which(name: str) -> str | None:
    return shutil.which(name)


# ----------------------------------------------------------------------------- the command
def resolve_command(
    override: Path | None = None,
    *,
    executable: str | None = None,
    frozen: bool | None = None,
    windows: bool | None = None,
) -> list[str]:
    """The command line a host should run to start the server, as absolute paths.

    In order: an explicit override (run as ``<override> mcp serve``); the frozen executable when
    PyInstaller says this process is one; the console script installed beside the running
    interpreter, so the host starts the same engine this command belongs to; else the interpreter
    itself with ``-m arcavex``, which works wherever the package imports.

    Paths are made absolute without following symlinks: on macOS and Linux a virtual
    environment's ``python`` is a symlink to the base interpreter, and resolving it would register
    an interpreter that cannot import the engine.
    """
    if override is not None:
        return [os.path.abspath(os.path.expanduser(str(override))), "mcp", "serve"]
    exe = Path(os.path.abspath(executable if executable is not None else sys.executable))
    is_frozen = frozen if frozen is not None else bool(getattr(sys, "frozen", False))
    if is_frozen:
        return [str(exe), "mcp", "serve"]
    is_windows = windows if windows is not None else os.name == "nt"
    script = exe.with_name("arcavex.exe" if is_windows else "arcavex")
    if script.is_file():
        return [str(script), "mcp", "serve"]
    return [str(exe), "-m", "arcavex", "mcp", "serve"]


def shell_join(argv: list[str]) -> str:
    """Join a command for a person to paste into a shell.

    Double quotes are the one quoting both ``cmd``/PowerShell and a POSIX shell accept, so a token
    with whitespace gets those; everything else is left bare so the line reads as typed.
    """
    return " ".join(f'"{arg}"' if re.search(r"\s", arg) else arg for arg in argv)


# ------------------------------------------------------------------------------- the hosts
@dataclass(frozen=True)
class _Machine:
    """What the hosts need to know about this machine; every field is injectable for tests."""

    which: Which
    run: Runner
    platform: str
    home: Path
    environ: Mapping[str, str]


@dataclass(frozen=True)
class _Probe:
    """One host's state, read without writing anything."""

    available: bool
    registered: bool
    location: str
    snippet: str
    #: How to get the host, for the host-not-found hint.
    install_hint: str
    note: str | None = None


def _run_steps(machine: _Machine, steps: list[list[str]]) -> Diagnostic | None:
    """Run host-CLI commands in order; the first failure is reported with what the CLI said."""
    for argv in steps:
        try:
            result = machine.run(argv)
        except (OSError, subprocess.SubprocessError) as exc:
            return _cli_failed(argv, str(exc))
        if result.returncode != 0:
            said = (result.stderr or result.stdout or "").strip()
            return _cli_failed(argv, said or f"exit code {result.returncode}")
    return None


def _cli_failed(argv: list[str], said: str) -> Diagnostic:
    return diagnostic(
        "ARC-MCP-004",
        f"'{shell_join(argv[:3])}' failed: {said}",
        hint=(
            "Fix what the host CLI reported and run this again, or register by hand with the "
            "snippet from 'arcavex mcp install --print'."
        ),
    )


def _write_failed(path: Path, what: str) -> Diagnostic:
    return diagnostic(
        "ARC-MCP-004",
        f"Could not update {path}: {what}",
        hint=(
            "Nothing was changed. Fix or move the file and run this again, or paste the snippet "
            "from 'arcavex mcp install --print' into it yourself."
        ),
    )


def _backup_then_write(path: Path, previous: str, new_text: str) -> None:
    """Replace ``path`` atomically, leaving its previous content beside it as ``<name>.bak``.

    The backup is written first, so a failure between the two leaves the original untouched
    and the copy present rather than the other way round.
    """
    if previous:
        atomic_write_text(path.with_name(path.name + ".bak"), previous)
    atomic_write_text(path, new_text)


def _read_if_present(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


class _ClaudeCode:
    """Claude Code: registered through its own CLI, at user scope.

    User scope because it is the one that works without a person approving anything: a project
    -scope entry sits in "pending approval" until someone accepts it in a session, which is the
    step a non-technical user does not know to take. ``~/.claude.json`` is the CLI's file, and its
    layout is the CLI's business; this never edits it.
    """

    key = "claude-code"
    label = "Claude Code"
    aliases: tuple[str, ...] = ()
    location = "claude mcp (user scope)"

    def snippet(self, command: list[str]) -> str:
        return shell_join(["claude", "mcp", "add", "-s", "user", SERVER_NAME, "--", *command])

    def probe(self, machine: _Machine, command: list[str]) -> _Probe:
        exe = machine.which("claude")
        return _Probe(
            available=exe is not None,
            registered=exe is not None and self._registered(machine, exe),
            location=self.location,
            snippet=self.snippet(command),
            install_hint=(
                "Install Claude Code (https://claude.com/claude-code) so 'claude' is on PATH"
            ),
            note="Registered for every project; 'claude mcp list' shows it under user scope.",
        )

    def _registered(self, machine: _Machine, exe: str) -> bool:
        # `claude mcp get NAME` exits 0 when the server exists in any scope and 1 otherwise.
        try:
            return machine.run([exe, "mcp", "get", SERVER_NAME]).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def register(
        self, machine: _Machine, command: list[str], *, replace: bool
    ) -> Diagnostic | None:
        exe = machine.which("claude")
        if exe is None:  # pragma: no cover - the caller probed availability first
            return _cli_failed(["claude"], "not found on PATH")
        steps: list[list[str]] = []
        if replace:
            steps.append([exe, "mcp", "remove", "-s", "user", SERVER_NAME])
        steps.append([exe, "mcp", "add", "-s", "user", SERVER_NAME, "--", *command])
        return _run_steps(machine, steps)


class _ClaudeDesktop:
    """Claude Desktop: a JSON file the app reads at start-up, edited in place.

    The app has no CLI, so the file is the only route. It is rewritten with every other key kept
    and the existing indentation, atomically, with a ``.bak`` of the previous content beside it.
    Only attempted when the app's config directory exists — that is what "installed" means here.
    """

    key = "claude-desktop"
    label = "Claude Desktop"
    aliases: tuple[str, ...] = ("desktop",)

    def config_path(self, machine: _Machine) -> Path:
        if machine.platform == "win32":
            base = Path(machine.environ.get("APPDATA") or machine.home / "AppData" / "Roaming")
        elif machine.platform == "darwin":
            base = machine.home / "Library" / "Application Support"
        else:
            base = Path(machine.environ.get("XDG_CONFIG_HOME") or machine.home / ".config")
        return base / "Claude" / "claude_desktop_config.json"

    @staticmethod
    def entry(command: list[str]) -> dict[str, object]:
        return {"command": command[0], "args": list(command[1:])}

    def snippet(self, command: list[str]) -> str:
        return json.dumps(
            {"mcpServers": {SERVER_NAME: self.entry(command)}}, indent=2, ensure_ascii=False
        )

    def probe(self, machine: _Machine, command: list[str]) -> _Probe:
        path = self.config_path(machine)
        available = path.parent.is_dir()
        registered = False
        if available and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            servers = data.get("mcpServers") if isinstance(data, dict) else None
            registered = isinstance(servers, dict) and SERVER_NAME in servers
        return _Probe(
            available=available,
            registered=registered,
            location=str(path),
            snippet=self.snippet(command),
            install_hint=(
                "Install Claude Desktop (https://claude.ai/download) and open it once so its "
                "config directory exists"
            ),
            note="Quit and reopen Claude Desktop after registering; it reads the file at start.",
        )

    def register(
        self, machine: _Machine, command: list[str], *, replace: bool
    ) -> Diagnostic | None:
        path = self.config_path(machine)
        try:
            previous = _read_if_present(path)
        except OSError as exc:
            return _write_failed(path, exc.strerror or str(exc))
        data: object = {}
        if previous.strip():
            try:
                data = json.loads(previous)
            except ValueError as exc:
                return _write_failed(path, f"the file is not valid JSON ({exc})")
        if not isinstance(data, dict):
            return _write_failed(path, "the top level is not a JSON object")
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            return _write_failed(path, "'mcpServers' is not a JSON object")
        servers[SERVER_NAME] = self.entry(command)
        new_text = json.dumps(data, indent=_json_indent(previous), ensure_ascii=False) + "\n"
        try:
            _backup_then_write(path, previous, new_text)
        except OSError as exc:
            return _write_failed(path, exc.strerror or str(exc))
        return None


def _json_indent(text: str) -> int | str:
    """The indentation an existing JSON file uses (two spaces when there is nothing to read)."""
    match = re.search(r'^([ \t]+)"', text, re.MULTILINE)
    if match is None:
        return 2
    return "\t" if "\t" in match.group(1) else len(match.group(1))


# A `[mcp_servers.arcavex]` table header, bare or with the key quoted, with an optional comment.
_CODEX_HEADER = re.compile(
    r'^[ \t]*\[[ \t]*mcp_servers[ \t]*\.[ \t]*"?' + SERVER_NAME + r'"?[ \t]*\][ \t]*(?:#.*)?$',
    re.MULTILINE,
)
# Any table or array-of-tables header: where the section above ends.
_ANY_HEADER = re.compile(r"^[ \t]*\[", re.MULTILINE)


class _Codex:
    """Codex: through its CLI when present, else by editing ``~/.codex/config.toml``.

    ``codex mcp add`` is preferred because the CLI owns the file. Without it, the table is appended
    to (or, with ``--force``, replaced in) the existing file by text, so nothing else in it is
    reformatted; the file is parsed first so an entry in a layout this cannot rewrite is refused
    rather than duplicated. ``CODEX_HOME`` relocates the directory, as it does for Codex itself.
    """

    key = "codex"
    label = "Codex CLI"
    aliases: tuple[str, ...] = ("chatgpt",)
    note = (
        "The ChatGPT desktop app cannot run a local MCP server; Codex is the OpenAI host that can."
    )

    def config_path(self, machine: _Machine) -> Path:
        home = Path(machine.environ.get("CODEX_HOME") or machine.home / ".codex")
        return home / "config.toml"

    @staticmethod
    def table(command: list[str]) -> str:
        # json.dumps produces valid TOML basic strings and arrays, backslashes escaped.
        return (
            f"[mcp_servers.{SERVER_NAME}]\n"
            f"command = {json.dumps(command[0], ensure_ascii=False)}\n"
            f"args = {json.dumps(list(command[1:]), ensure_ascii=False)}\n"
        )

    def probe(self, machine: _Machine, command: list[str]) -> _Probe:
        exe = machine.which("codex")
        path = self.config_path(machine)
        registered = False
        if path.is_file():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                data = {}
            servers = data.get("mcp_servers")
            registered = isinstance(servers, dict) and SERVER_NAME in servers
        return _Probe(
            available=exe is not None or path.parent.is_dir(),
            registered=registered,
            location=str(path),
            snippet=self.table(command),
            install_hint=(
                "Install Codex (npm install -g @openai/codex) and run it once so ~/.codex exists"
            ),
            note=self.note,
        )

    def register(
        self, machine: _Machine, command: list[str], *, replace: bool
    ) -> Diagnostic | None:
        path = self.config_path(machine)
        exe = machine.which("codex")
        if exe is not None:
            steps: list[list[str]] = []
            if replace:
                steps.append([exe, "mcp", "remove", SERVER_NAME])
            steps.append([exe, "mcp", "add", SERVER_NAME, "--", *command])
            return _run_steps(machine, steps)
        try:
            previous = _read_if_present(path)
        except OSError as exc:
            return _write_failed(path, exc.strerror or str(exc))
        try:
            tomllib.loads(previous)
        except tomllib.TOMLDecodeError as exc:
            return _write_failed(path, f"the file is not valid TOML ({exc})")
        table = self.table(command)
        if replace:
            rewritten = _replace_codex_table(previous, table)
            if rewritten is None:
                return _write_failed(
                    path,
                    f"the existing '{SERVER_NAME}' entry is not a [mcp_servers.{SERVER_NAME}] "
                    "table this command can rewrite",
                )
            new_text = rewritten
        else:
            new_text = previous
            if new_text and not new_text.endswith("\n"):
                new_text += "\n"
            if new_text.strip():
                new_text += "\n"
            new_text += table
        try:
            _backup_then_write(path, previous, new_text)
        except OSError as exc:
            return _write_failed(path, exc.strerror or str(exc))
        return None


def _replace_codex_table(text: str, table: str) -> str | None:
    """Swap the ``[mcp_servers.arcavex]`` section for ``table``, touching nothing else.

    The section runs from its header to the next table header (or the end of the file), so a
    sub-table such as ``[mcp_servers.arcavex.env]`` is kept. ``None`` when the entry is not
    written as such a header — an inline table or dotted keys — because appending a second
    definition would make the file invalid TOML.
    """
    header = _CODEX_HEADER.search(text)
    if header is None:
        return None
    following = _ANY_HEADER.search(text, header.end())
    end = following.start() if following else len(text)
    replacement = table + "\n" if following else table
    return text[: header.start()] + replacement + text[end:]


_HOSTS: tuple[_ClaudeCode | _ClaudeDesktop | _Codex, ...] = (
    _ClaudeCode(),
    _ClaudeDesktop(),
    _Codex(),
)
_HOSTS_BY_KEY = {key: host for host in _HOSTS for key in (host.key, *host.aliases)}


# ----------------------------------------------------------------------------- the service
class McpHostService:
    """Registers the MCP server with every AI host present on this machine."""

    def __init__(
        self,
        *,
        which: Which | None = None,
        runner: Runner | None = None,
        platform: str | None = None,
        home: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._which = which
        self._runner = runner
        self._platform = platform
        self._home = home
        self._environ = environ

    def _machine(self) -> _Machine:
        # Read at call time, not construction: the facade is built once, and a test (or a person)
        # may change HOME between calls. The user's real home, not ARCAVEX_HOME — a host keeps its
        # config in its own directory, independent of where the engine keeps fonts.
        return _Machine(
            which=self._which or _default_which,
            run=self._runner or _default_runner,
            platform=self._platform or sys.platform,
            home=self._home or Path.home(),
            environ=self._environ if self._environ is not None else os.environ,
        )

    def list_targets(self, *, command: Path | None = None) -> McpInstallReport:
        """Describe every host and whether the server is registered there; writes nothing."""
        argv = resolve_command(command)
        machine = self._machine()
        return McpInstallReport(
            ok=True,
            command=argv,
            targets=[_info(host, host.probe(machine, argv)) for host in _HOSTS],
        )

    def install(
        self,
        *,
        targets: list[str] | None = None,
        command: Path | None = None,
        force: bool = False,
    ) -> McpInstallReport:
        """Register the server with each requested host; never raises.

        With no ``targets``, every host present on this machine is registered and the absent ones
        are reported as notices — the common case is a person who wants their assistant to reach
        the engine, whichever assistant that is. A host named explicitly and not found is an error.
        """
        argv = resolve_command(command)
        explicit = bool(targets)
        keys = targets or [host.key for host in _HOSTS]
        unknown = [k for k in keys if k not in _HOSTS_BY_KEY]
        if unknown:
            known = ", ".join(host.key for host in _HOSTS)
            aliases = ", ".join(f"{a} = {h.key}" for h in _HOSTS for a in h.aliases)
            return McpInstallReport(
                ok=False,
                command=argv,
                diagnostics=[
                    diagnostic(
                        "ARC-MCP-001",
                        f"Unknown MCP host {unknown[0]!r}",
                        hint=f"Use one of: {known} (aliases: {aliases}).",
                    )
                ],
            )
        wanted_keys = {_HOSTS_BY_KEY[k].key for k in keys}
        wanted = [host for host in _HOSTS if host.key in wanted_keys]

        machine = self._machine()
        infos: list[McpTargetInfo] = []
        installed: list[str] = []
        diagnostics: list[Diagnostic] = []
        for host in wanted:
            probe = host.probe(machine, argv)
            info = _info(host, probe)
            if not probe.available:
                # Asked for by name, a missing host is an error and the hint carries the whole
                # snippet — that person is about to do it by hand. Swept up by the default run,
                # it is a notice, kept short so a success is not buried under paste blocks.
                if explicit:
                    hint = (
                        f"{probe.install_hint}, then run this again. Or register it by hand — "
                        f"paste this ('arcavex mcp install --print' shows it too):\n"
                        f"{probe.snippet}"
                    )
                else:
                    hint = (
                        f"{probe.install_hint}, then run this again; or run "
                        "'arcavex mcp install --print' for the snippet to paste by hand."
                    )
                diagnostics.append(
                    diagnostic(
                        "ARC-MCP-002",
                        f"{host.label} is not installed on this machine",
                        severity="error" if explicit else "info",
                        hint=hint,
                    )
                )
            elif probe.registered and not force:
                diagnostics.append(
                    diagnostic(
                        "ARC-MCP-003",
                        f"{host.label} already has an '{SERVER_NAME}' server ({probe.location})",
                        severity="warning",
                        hint="Pass --force to replace it with this engine's command.",
                    )
                )
            else:
                failure = host.register(machine, argv, replace=probe.registered)
                if failure is not None:
                    diagnostics.append(failure)
                else:
                    installed.append(host.key)
                    info = info.model_copy(update={"registered": True})
            infos.append(info)

        return McpInstallReport(
            # Absent hosts are notices, not failures: a machine with only Claude Desktop on it
            # has done everything it can. A refusal or a failed write is not "ok" on its own.
            ok=bool(installed) or not any(d.severity != "info" for d in diagnostics),
            command=argv,
            targets=infos,
            installed=installed,
            diagnostics=diagnostics,
        )


def _info(host: _ClaudeCode | _ClaudeDesktop | _Codex, probe: _Probe) -> McpTargetInfo:
    return McpTargetInfo(
        key=host.key,
        label=host.label,
        location=probe.location,
        available=probe.available,
        registered=probe.registered,
        snippet=probe.snippet,
        note=probe.note,
    )

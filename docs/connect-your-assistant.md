# Connect your assistant

Arcavex is a rendering engine; an AI assistant drives it. The assistant reaches the engine over
MCP — the Model Context Protocol, a standard way for an assistant to run a local program and use it
as a set of tools. Before that can happen, the assistant's application has to be told the engine
exists. That is this page, and it is one command.

## The one command

Open a terminal (PowerShell on Windows, Terminal on macOS) and run:

```console
$ arcavex mcp install
```

It finds every assistant installed on this machine — Claude Code, Claude Desktop, Codex — and
registers the engine with each one. It prints what it registered, where, and what to do next.
Assistants that are not installed are listed as notices, not errors: a machine with only Claude
Desktop on it is done after this one command.

If the terminal says `arcavex` is not recognised, the engine is not on your PATH yet; see
[install.md](install.md).

## Then, for each assistant

Every host reads its configuration when it starts, so the last step is always a fresh start.

| Assistant | What to do | How to check it worked |
|---|---|---|
| Claude Desktop | Quit it completely and open it again. | The tools menu in the message box lists `arcavex`. |
| Claude Code | Open a new session; a running one does not pick it up. | `claude mcp list` shows `arcavex` under user scope. |
| Codex | Start a new session. | `codex mcp list` shows `arcavex`. |

Then ask the assistant to design something. The engine also ships a design skill that teaches an
assistant how to use it well; `arcavex skill install` puts that where Claude Code or Codex reads it
([cli.md](cli.md#skill)). Claude Desktop reads the same document through the server itself, so it
needs nothing more.

## Doing it by hand

If a host is installed somewhere the command does not find it, or you want to see exactly what it
would do first, `arcavex mcp install --print` writes nothing and prints the text to paste for each
host. The snippets below show the shape; your path will differ, and the command prints the real one.

**Claude Code** — run this in a terminal:

```console
$ claude mcp add -s user arcavex -- C:\Users\you\arcavex\.venv\Scripts\arcavex.exe mcp serve
```

**Claude Desktop** — open `claude_desktop_config.json` (Windows: `%APPDATA%\Claude`; macOS:
`~/Library/Application Support/Claude`; Linux: `~/.config/Claude`) and add the `arcavex` entry
under `mcpServers`, keeping anything already there:

```json
{
  "mcpServers": {
    "arcavex": {
      "command": "C:\\Users\\you\\arcavex\\.venv\\Scripts\\arcavex.exe",
      "args": ["mcp", "serve"]
    }
  }
}
```

**Codex** — add this to `~/.codex/config.toml`:

```toml
[mcp_servers.arcavex]
command = "C:\\Users\\you\\arcavex\\.venv\\Scripts\\arcavex.exe"
args = ["mcp", "serve"]
```

**ChatGPT** — the ChatGPT desktop app cannot run a local MCP server, so there is nothing to paste
into it. `arcavex mcp install --target chatgpt` registers with Codex, OpenAI's host that can.

## Checking and changing

- `arcavex mcp install --list` shows each host, where its registration lives, and whether
  `arcavex` is registered there, without writing anything.
- Running `install` again when a host is already registered stops with `ARC-MCP-003` rather than
  overwriting; `--force` replaces the entry, which is what you want after moving the engine.
- The command registered is the engine that ran `mcp install`, as an absolute path, and it is
  printed every time so you can see it. `--command PATH` registers a different executable.
- When the command edits a file (Claude Desktop, and Codex without its CLI), everything else in the
  file is kept and the previous content stays beside it as `.bak`.
- `arcavex mcp install --json` returns the same report as data.

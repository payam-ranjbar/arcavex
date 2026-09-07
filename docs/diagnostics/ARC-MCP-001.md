# ARC-MCP-001 — Unknown MCP host

'arcavex mcp install --target' was given a name that is not a host this command knows how to register with. The hosts are fixed because each has its own registration mechanism — Claude Code's and Codex's CLIs, Claude Desktop's config file — and a name outside that set has none.

**Typical fix:** Use claude-code, claude-desktop, or codex ('desktop' and 'chatgpt' are aliases). For any other MCP client, 'arcavex mcp install --print' shows the command line to register as a stdio server.

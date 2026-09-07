# ARC-MCP-003 — MCP server already registered with this host

The host already has a server named 'arcavex'. Registration stops rather than replacing it, because it may point at a different engine on purpose — a frozen build, another virtual environment — or carry settings a person added.

**Typical fix:** Pass '--force' to replace it with this engine's command; '--list' shows which hosts are registered.

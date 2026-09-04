# ARC-MCP-002 — MCP host not found on this machine

The host is not installed here: 'claude' or 'codex' is not on PATH, or Claude Desktop's config directory does not exist. Nothing was written. In a default run (no --target) this is an informational notice, because a machine with only one assistant on it has done everything it can; for a host named with --target it is an error, and the hint carries the exact snippet to paste by hand.

**Typical fix:** Install the host and run 'arcavex mcp install' again, or register by hand with the snippet from 'arcavex mcp install --print'.

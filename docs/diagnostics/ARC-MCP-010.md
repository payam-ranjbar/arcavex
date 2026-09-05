# ARC-MCP-010 — Unknown tool argument

An MCP tool call carried an argument key the tool does not declare (for example 'format' on arcavex_template_new, or 'scale' on arcavex_render). The call is refused before anything runs: an unknown option that was silently dropped would look exactly like one that took effect.

**Typical fix:** Use only the arguments in the tool's inputSchema ('arcavex mcp tools --json' lists them, and the hint names them); the option you meant may belong to another tool.

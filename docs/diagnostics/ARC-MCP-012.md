# ARC-MCP-012 — Invalid tool argument value

An MCP tool call passed a value of the wrong type, or outside the accepted values, for an argument (for example dpi: 'high', or a mode that is not one of the listed literals).

**Typical fix:** Pass a value of the type the hint states; lists and mappings are JSON values, not prose.

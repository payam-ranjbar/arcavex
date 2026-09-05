# ARC-FX-912 — Invalid shape-generator parameters

A shape generator's parameters failed validation against its schema (an unknown name, a wrong type, or an out-of-range value), or the generator raised while building its path. The message lists every offending field and the hint enumerates the generator's real parameters with their types, defaults, and ranges.

**Typical fix:** Fix the named fields against the parameters the hint lists. 'arcavex shapes list' (MCP: arcavex_shape_list) lists every registered generator and its schema, and 'arcavex shapes inspect <name>' shows one; the same table is in docs/template-schema.md under 'Shape generator parameters'.

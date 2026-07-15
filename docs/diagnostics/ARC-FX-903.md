# ARC-FX-903 — Malformed effect list

A node's 'effects' is not a list, or an entry is neither a name, a '{name, params}' mapping, nor a '{preset: name}' reference.

**Typical fix:** Write 'effects:' as a list where each item is a name, '{name, params}', or '{preset: name}'.

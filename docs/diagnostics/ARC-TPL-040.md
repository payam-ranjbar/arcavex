# ARC-TPL-040 — Malformed text runs

A text node's 'runs' is not a list, or a run entry is neither a string nor a {text, ...} mapping.

**Typical fix:** Write 'runs:' as a list of strings or mappings, each with a 'text' field.

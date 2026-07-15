# ARC-LIB-003 — Ambiguous bare template name

A bare template name was used but the library declares no default version for it, so Arcavex will not silently pick 'latest' for a recorded render (spec §5.1).

**Typical fix:** Reference an explicit 'name@version', or set a default alias for the template.

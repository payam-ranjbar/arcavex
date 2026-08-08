# ARC-INT-011 — Executable artifact identity unavailable

Arcavex is running through an interpreter rather than a frozen executable, so there is no Arcavex executable artifact whose path and SHA-256 can be reported honestly. The Python interpreter is deliberately not presented as the engine artifact.

**Typical fix:** Use the frozen Arcavex executable when a release artifact identity is required. In an interpreted development run, no action is required.

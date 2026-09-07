# ARC-PRJ-013 — Invalid proposal record

A proposal has an invalid canonical project path, base project revision, actor, created timestamp, state, or command payload that cannot be represented as JSON.

**Typical fix:** Provide a canonical project path, SHA-256 base revision, actor identity, timezone-aware timestamp, and JSON-serializable command payload.

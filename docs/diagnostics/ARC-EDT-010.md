# ARC-EDT-010 — Invalid editor transaction

A submitted payload is not a valid semantic transaction: an unknown command kind, an undeclared key, non-finite geometry, a non-canonical project path, or a malformed revision. Nothing was executed.

**Typical fix:** Compose transactions against the editor-transaction schema and re-submit.

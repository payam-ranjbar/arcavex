# ARC-EDT-003 — Unreadable history record skipped

A JSON record under .arcavex/history cannot be decoded or validated. The record is skipped; undo/redo of the remaining entries still works.

**Typical fix:** Remove the named file under .arcavex/history to clear the warning.

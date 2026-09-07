# ARC-PRJ-010 — Malformed proposal queue entry

A JSON record under .arcavex/pending cannot be decoded or validated, does not match its filename, or names a different canonical project. Other valid records are still listed.

**Typical fix:** Repair or remove the named queue JSON record, then list proposals again.

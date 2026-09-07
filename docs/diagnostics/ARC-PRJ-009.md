# ARC-PRJ-009 — Invalid proposal command ID

A proposal command ID is not a canonical lowercase UUIDv4, so it cannot safely and deterministically identify a queue filename.

**Typical fix:** Generate a new canonical UUIDv4 and submit the proposal using its lowercase string.

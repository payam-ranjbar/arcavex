# ARC-TPL-058 — Duplicate repeat key

Two iterations of a repeat produced the same key, which would collide expanded IDs.

**Typical fix:** Make the key expression unique per item.

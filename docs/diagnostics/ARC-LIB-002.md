# ARC-LIB-002 — Library version already published

'template publish' refuses to overwrite an existing version directory, because published versions are immutable — a change is always a new version (spec §5.5).

**Typical fix:** Publish under a new version number instead of reusing an existing one.

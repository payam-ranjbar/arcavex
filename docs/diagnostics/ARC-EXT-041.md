# ARC-EXT-041 — Enabled extension not removed

'ext remove' named an extension that is enabled, and --force was not given. Its components are live for every run, so removing it silently would make each template that uses them fail on the next start with an unknown-effect error that says nothing about the removal.

**Typical fix:** Disable it first with 'arcavex ext disable <name>' and remove it again, or pass --force to remove it while enabled.

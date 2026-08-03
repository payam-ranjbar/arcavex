# ARC-EXT-030 — Extension imports outside the SDK surface

A source file imports an Arcavex module other than the public 'arcavex.sdk'. This is an authoring/reliability rule, not a security boundary — extensions are insulated from engine internals so they keep working across engine changes.

**Typical fix:** Import only from 'arcavex.sdk', which re-exports the contracts, helpers, and IR value types an extension may use.

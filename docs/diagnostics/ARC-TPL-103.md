# ARC-TPL-103 — Locale content shadowed by the project's data

A template supplies text for this locale through 'locales.<name>.data', and the project's own data file sets the same keys. User data outranks template data, so the locale's copy is not what renders — a right-to-left layout can come out holding the other language's words, which validates and looks deliberate.

**Typical fix:** Remove the key from the project's data file, or move the locale's copy into a sibling '<data>.<locale>.yaml', which is applied over the base data instead.

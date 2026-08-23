# ARC-TPL-102 — Locale rendered without content of its own

A locale whose text direction differs from the content was applied, but neither an inline 'locales.<name>.data' nor a sibling '<data>.<locale>.yaml' supplied any text for it. The direction and digit rules still apply, so untranslated copy is bidi-reordered: an English time range renders reversed while looking entirely normal.

**Typical fix:** Supply the locale's copy, or render without --locale to see the source direction.

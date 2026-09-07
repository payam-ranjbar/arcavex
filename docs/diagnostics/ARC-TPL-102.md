# ARC-TPL-102 — Locale applied to copy written in another script

A locale whose text direction differs from the source was applied, but none of the copy it was given reads in that direction: neither an inline 'locales.<name>.data' nor a sibling '<data>.<locale>.yaml' supplied any text, and the data (or the template's own text) carries no character of the locale's script. The direction and digit rules still apply, so untranslated copy is bidi-reordered: an English time range renders reversed while looking entirely normal. Data already written in the locale's script is the intended use and is not reported.

**Typical fix:** Pass data written in the locale (a data file, a sibling '<data>.<locale>.yaml' overlay, or inline 'locales.<name>.data'), or render without a locale to see the source direction.

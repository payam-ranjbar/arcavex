# ARC-TPL-099 — Invalid locale setting

A locale entry has an unknown setting key or an out-of-range value. Locale files are validated for shape now even though locale application is Phase 2, so mistakes surface while you author. Direction must be 'ltr' or 'rtl'; digits must be one of 'en', 'fa', 'latn', 'arab'; fonts and data must be mappings and patch a list.

**Typical fix:** Correct the flagged key or value. The known per-locale settings are direction, digits, fonts, data, and patch.

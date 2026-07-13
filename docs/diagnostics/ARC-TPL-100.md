# ARC-TPL-100 — Undeclared locale

A locale was requested with --locale that the template does not declare, so its direction, digits, fonts, data, and patch are unknown. Arcavex never silently ignores a requested locale.

**Typical fix:** Declare the locale under 'locales:' in the template, or request one the template already defines.

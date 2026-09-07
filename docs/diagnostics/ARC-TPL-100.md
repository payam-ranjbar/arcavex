# ARC-TPL-100 — Undeclared locale

A requested locale (--locale on the CLI, 'locale' over MCP) is not declared by the template, so its direction, digits, fonts, data, and patch are unknown. Arcavex never silently ignores a requested locale.

**Typical fix:** Declare the locale under 'locales:' in the template, or request one the template already defines.

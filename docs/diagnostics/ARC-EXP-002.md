# ARC-EXP-002 — Image encoding failed

The rendered surface could not be encoded to the requested raster format (PNG, JPEG, or WebP). This is an internal encoder failure, not a bad option.

**Typical fix:** Retry the render; if it persists, report it with the template and format. Check 'arcavex doctor' confirms the Skia build supports the format.

# ARC-EXP-003 — PDF export failed

The rendered surface could not be embedded into a PDF — Skia's PDF backend could not encode the raster or create the document.

**Typical fix:** Retry the render; if it persists, report it. Check 'arcavex doctor' confirms Skia's PDF backend is available.

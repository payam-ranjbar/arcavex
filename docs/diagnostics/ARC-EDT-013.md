# ARC-EDT-013 — No usable target format for a format-scoped edit

The transaction asked for scope 'format' — write each command as an override in formats.<name>.patch so only that format changes — but target.format named no format, named one the template does not define, or the format's spec is not a mapping a patch list can be added to. Nothing was changed.

**Typical fix:** Set target: {format: <name>} to a format the template defines, or use scope: shared to edit the authored node every format renders.

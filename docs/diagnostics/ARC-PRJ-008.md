# ARC-PRJ-008 — Invalid project UI metadata

The optional project.ui.yaml sidecar is not a version 1 mapping or contains an unsupported layer/workspace field, invalid lock value, or invalid #RRGGBB color.

**Typical fix:** Use version 1, key layer metadata by stable authored ID, and keep workspace state to the documented project-local fields.

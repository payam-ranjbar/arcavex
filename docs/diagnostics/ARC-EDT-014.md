# ARC-EDT-014 — Command cannot be scoped to one format

Under scope 'format' a command must have a per-format form: a field write the engine can express as a 'set' op in formats.<name>.patch. Structural commands (reorder, reparent, duplicate, delete, group, splice_children) change the tree every format shares, and set_display_name writes project-wide UI metadata, so neither can be written for one format alone. Nothing was changed.

**Typical fix:** Use scope: shared for structural changes and display names. A per-format structure needs a hand-written formats.<name>.patch with insert_before, insert_after, or remove ops (arcavex_template_patch).

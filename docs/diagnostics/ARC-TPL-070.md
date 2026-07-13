# ARC-TPL-070 — Scaffold target already exists

'template new' refuses to write into a directory that already exists and contains files, so it can never overwrite work you already have. A path that does not yet exist, or an empty directory, is accepted.

**Typical fix:** Point 'template new' at a new or empty directory, or move the existing contents aside first. To evolve a template you already have, edit it directly rather than re-scaffolding over it.

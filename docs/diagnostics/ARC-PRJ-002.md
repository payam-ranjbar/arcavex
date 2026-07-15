# ARC-PRJ-002 — Invalid project manifest

A project.yaml is missing a required field (at least 'name' and 'template'), is not a mapping, declares no formats to render, or its override file is not a list of patch operations.

**Typical fix:** Fix project.yaml so it has 'name', 'template', and a 'formats:' list; write overrides as a YAML list of set/remove/insert ops.

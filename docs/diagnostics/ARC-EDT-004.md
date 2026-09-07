# ARC-EDT-004 — Structural edit target is invalid

A structural edit named a node or parent that does not exist, addressed a node whose id is duplicated, tried to give children to a non-group node, grouped layers that are not siblings, or chose a group id that already exists. Nothing was changed.

**Typical fix:** Inspect the layer tree for current ids and structure, then retry the edit.

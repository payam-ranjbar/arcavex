# ARC-EDT-005 — Structural edit would corrupt the tree

The edit would delete or reparent the root node, or move a node into its own descendant and create a cycle. These operations are never valid; nothing was changed.

**Typical fix:** Choose a target outside the subtree being moved, and leave the root in place.

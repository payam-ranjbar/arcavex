# ARC-LAY-040 — Repeated siblings overlap

A 'repeat' expanded more than one sibling node, and because constraint values are static in this build (no expressions inside constraints, no layout stacks yet) every expanded sibling inherits the same anchors and size — so they resolve to identical bounds and stack on top of one another. This is a warning, not an error: the render still succeeds.

**Typical fix:** Give each repeated item a distinct literal anchor when the count is fixed, or wait for layout stacks (Phase 2), which position repeated children automatically.

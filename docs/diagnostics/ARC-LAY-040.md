# ARC-LAY-040 — Repeated siblings overlap

A 'repeat' expanded more than one sibling node in an *absolute* group, and every expanded sibling carries the same fixed anchors and size — so they resolve to identical bounds and stack on top of one another. This is a warning, not an error: the render still succeeds. It does not fire inside a stack (the stack positions each child) nor when the anchors carry per-item expressions that separate them.

**Typical fix:** Give each item a distinct anchor with a per-item offset (e.g. 'top: parent.top+{{ loop.index * 90 }}pt'), or wrap the repeat in a 'layout: vstack'/'hstack' group so the stack positions each child.

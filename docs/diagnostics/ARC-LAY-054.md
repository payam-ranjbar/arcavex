# ARC-LAY-054 — Stack child has position anchors

A child of an hstack/vstack group declares position anchors, but a stack positions its own children along the main axis, so anchors would contradict it.

**Typical fix:** Remove the 'anchor' block from the stack child; use gap, padding, and the stack's alignment to position it. Size modes still apply.

# ARC-LAY-052 — Sibling anchor cycle

Two or more sibling nodes anchor to each other in a loop, so no resolution order exists. The message names the full cycle.

**Typical fix:** Break the loop so at least one node in it anchors to the parent or to a node resolved before it.

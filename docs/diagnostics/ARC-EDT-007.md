# ARC-EDT-007 — Sibling anchors depend on this layer

Deleting the addressed layer would orphan constraint expressions on sibling layers that anchor to it. The dependents are named in the message; nothing was changed.

**Typical fix:** Delete the dependent layers too, or re-anchor them to another sibling first.

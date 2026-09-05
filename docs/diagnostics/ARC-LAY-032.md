# ARC-LAY-032 — Node missing a size

A node has constraints but no complete size for one or both axes. Anchors only position a node; every axis also needs a size, and a second anchor is not a way to give one (that is ARC-LAY-031).

**Typical fix:** Add 'size: {w: ..., h: ...}' — each of fixed (e.g. 100px), a %, 'fill', 'fit_content' (text only), or {aspect: 'W:H'}. To span the parent on an axis use 'fill' with one anchor on that axis; for an inset frame, anchor one edge and use a % of the parent, or wrap the content in a 'layout: vstack' group with 'padding' and give the child 'size: {w: fill, h: fill}'.

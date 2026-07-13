# ARC-LAY-032 — Node missing a size

A node has constraints but no complete size for one or both axes.

**Typical fix:** Add 'size: {w: ..., h: ...}' — each of fixed (e.g. 100px), a %, 'fill', 'fit_content', or {aspect: 'W:H'}.

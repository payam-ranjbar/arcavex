# ARC-IR-016 — Invalid transform scale

A transform scale component is zero, negative, or not a finite number. A zero scale collapses the node to nothing while it stays selectable, and a negative one mirrors — a distinct operation this vocabulary does not express.

**Typical fix:** Use a positive number, or [sx, sy] with both components positive.

# ARC-LAY-056 — Wrapping stacks not supported yet

A stack group set 'wrap: true', but wrapping (flowing children onto multiple rows or columns) is deferred in this build rather than faked.

**Typical fix:** Lay wrapped rows out explicitly with nested stacks for now, or drop 'wrap'.

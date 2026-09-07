# ARC-LAY-021 — Stack sizes to its content but a child sizes to the stack

A stack uses 'fit_content' on an axis while one of its children asks for 'fill' or a percentage of that same axis. Each is waiting for the other, so neither has a size.

**Typical fix:** Give the child a fixed size or 'fit_content' on that axis, or give the stack a size of its own.

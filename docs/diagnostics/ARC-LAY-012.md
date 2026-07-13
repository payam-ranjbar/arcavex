# ARC-LAY-012 — Invalid anchor offset

An anchor offset could not be parsed into a fixed distance. The most common cause is a '{{ … }}' expression inside a constraint (e.g. 'parent.left + {{ i*240 }}px'): constraint values are static in this build — the evaluator does not run inside anchors, sizes, or offsets, so the braces are read as literal text and fail to parse. A malformed unit (missing number or unknown suffix) triggers it too.

**Typical fix:** Use a literal offset such as '+20px', '+20pt', or '-6mm'. Computed or per-item offsets are not available until layout stacks arrive in Phase 2; until then give each node a distinct literal anchor.

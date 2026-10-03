# ARC-TPL-069 — Numeric style expressions not supported

Numeric style fields accept literals, not template expressions, in this build.

**Typical fix:** Use a literal, a style_role, or format/locale node patches. For variable text length use fit.policy: shrink_to_fit with min_size and max_lines.

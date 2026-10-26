# ARC-TPL-036 — Unsupported shape

A shape node uses a shape kind not supported in this build. The primitives are rect, rrect, circle (inscribed in the shorter side) and ellipse (fills the box).

**Typical fix:** Use 'rect', 'rrect', 'circle' or 'ellipse', or a 'generator:' (starburst, speech_bubble, qr_code).

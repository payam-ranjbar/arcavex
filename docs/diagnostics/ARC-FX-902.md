# ARC-FX-902 — Invalid mask or effect parameters

A mask's or effect's parameters failed validation against the component's parameter schema (wrong name, type, or out-of-range value). Mask, shape and effect length params accept pt, mm, or px (px converts against the canvas DPI); a bare number is points and % has no absolute basis.

**Typical fix:** Check each parameter against the component's documented schema; the message lists every offending field so you can fix them in one pass.

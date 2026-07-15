# ARC-FX-902 — Invalid mask or effect parameters

A mask's or effect's parameters failed validation against the component's parameter schema (wrong name, type, or out-of-range value). Effect length params accept pt, mm, or px (px converts against the canvas DPI); mask length params are pt or mm.

**Typical fix:** Check each parameter against the component's documented schema; the message lists every offending field so you can fix them in one pass.

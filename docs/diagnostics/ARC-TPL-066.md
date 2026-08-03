# ARC-TPL-066 — Unknown format or canvas field

A 'formats.<name>' entry, or its 'canvas' block, carries a field the engine does not read. A format holds only 'canvas' and an optional 'patch'; a canvas holds 'width', 'height', 'dpi', and an optional 'bleed'. Every declared format is checked, not only the one being rendered.

**Typical fix:** Correct the field name; a canvas size belongs in 'width'/'height' and a per-format override belongs in 'patch'.

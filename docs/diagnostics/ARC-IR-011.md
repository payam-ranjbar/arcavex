# ARC-IR-011 — Invalid dimension

A dimension value could not be parsed, or a percentage was written where nothing exists to take a percentage of. In a size axis, a bare value must be a number with a unit (px/pt/mm), a percentage of the parent's extent, or one of the size keywords 'fill', 'fit_content', and 'aspect(W:H)'. Every other length — the style lengths (font_size, stroke_width, corner_radius, letter_spacing) and run overrides, a stack's gap and padding, a size axis's min/max clamps, a text fit's min_size, and the canvas itself — has no parent basis and takes px, pt, or mm only.

**Typical fix:** Use a number with a unit (e.g. '40pt', '210mm', '1080px'); in a size axis a percentage or a size keyword ('fill', 'fit_content', 'aspect(3:4)') is also valid.

# ARC-IR-030 — Invalid color

A color value could not be parsed. Colors are '#RGB'/'#RRGGBB'/'#RRGGBBAA', 'rgb()'/'rgba()' with in-range channels, a named CSS basic color, or 'none' / 'transparent' for no paint.

**Typical fix:** Use #hex, rgb()/rgba(), or a named color; for a stroke-only shape write 'fill: none' (an alias of 'transparent') with a 'stroke' and a 'stroke_width'.

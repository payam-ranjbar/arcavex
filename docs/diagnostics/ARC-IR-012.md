# ARC-IR-012 — Invalid size value

A size mapping is malformed: a percentage that will not parse, an 'aspect' ratio that is not 'W:H' with positive numbers, or a size mapping missing its 'value'/'aspect' key.

**Typical fix:** Use a value like '62%', an aspect like {aspect: '3:4'} (or 'aspect(3:4)'), or give the mapping a 'value:'.

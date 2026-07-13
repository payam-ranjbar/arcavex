# ARC-LAY-050 — Text overflow configured as error

A text node still overflows its resolved box after its fit policy ran, and the node's 'overflow' is set to 'error', so rendering fails rather than clipping or spilling. The message reports the shaped extent and the box extent.

**Typical fix:** Enlarge the box, reduce the text or font size, lower min_size for shrink_to_fit, or set overflow to 'clip' or 'allow'.

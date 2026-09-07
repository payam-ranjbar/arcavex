# ARC-TPL-104 — Paint style on a node that does not paint

A group or another non-painting node declares fill, stroke, stroke_width, or corner_radius. The fields are valid style vocabulary, so nothing rejected them, and nothing draws them either — the node renders exactly as if they were absent.

**Typical fix:** Give the node a shape child carrying the paint, or move the style onto the shape that should show it.

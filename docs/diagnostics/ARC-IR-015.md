# ARC-IR-015 — Invalid hit-test coordinate

A hit-test coordinate could not be converted to a number, or was NaN or infinity. Selection geometry accepts only finite canvas-point coordinates.

**Typical fix:** Pass finite numeric x_pt and y_pt values in canvas points.

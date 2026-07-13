# ARC-LAY-055 — Invalid aspect size mode

A node declares the 'aspect' size mode on both axes, or on one axis while the other axis cannot be resolved to a concrete value, so the derived dimension is undefined.

**Typical fix:** Give exactly one axis a concrete size (fixed, %, or fill); 'aspect' derives the other axis from it.

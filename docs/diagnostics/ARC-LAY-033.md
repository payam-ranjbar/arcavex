# ARC-LAY-033 — Fill-sized node overshoots its parent

A node sized 'fill' on an axis is anchored with an offset (or to a sibling's edge), so the far edge lands past the parent by that amount. 'fill' spans the whole parent; it does not shrink to what the anchor leaves. This is a warning, not an error: the render succeeds and the overshoot is clipped, which is what an author sees as "the frame is cut off on one side". The message names the overshoot in points.

**Typical fix:** For an inset, keep the anchor and size that axis as a percentage of the parent (or a fixed length), or wrap the content in a 'layout: vstack' group with 'padding' and give the child 'size: {w: fill, h: fill}'. If reaching past the parent is intended, the warning can be ignored.

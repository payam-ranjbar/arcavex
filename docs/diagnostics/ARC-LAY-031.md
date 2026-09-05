# ARC-LAY-031 — Node over-constrained

A node resolves more than one position on an axis — for example both 'left' and 'right' — because two anchors were given where the engine positions with exactly one anchor and one size per axis. Two anchors is almost always a way of saying "reach both edges", and that is said with the size.

**Typical fix:** Keep exactly one anchor per axis; size comes from the size spec. To span the parent, anchor one edge and size to it — 'anchor: {left: parent.left}', 'size: {w: fill}' (or a percentage). For an inset frame, anchor one edge with an offset and set that axis to a percentage of the parent, or wrap the content in a 'layout: vstack' group with 'padding' and give the child 'size: {w: fill, h: fill}'.

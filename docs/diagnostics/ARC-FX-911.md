# ARC-FX-911 — Geometry effect on an unsupported node

A geometry effect (e.g. torn-paper) rewrites a node's path, so it applies only to 'shape' and 'path' nodes; it was placed on a text, image, or group node.

**Typical fix:** Move the geometry effect onto a shape or path node, or remove it.

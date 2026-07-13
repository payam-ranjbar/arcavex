# ARC-IR-040 — Malformed mask declaration

A node's 'mask' is not a mapping, is missing its 'component' name, or its 'params' is not a mapping.

**Typical fix:** Write 'mask: {component: diamond_grid, params: {cell: 90pt, gutter: 6pt}}'.

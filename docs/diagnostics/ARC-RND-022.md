# ARC-RND-022 — Render surface exceeds the memory budget

The render surface would need more bytes than the per-render surface-memory budget allows (spec §8.3). Enforced from the canvas size and DPI before allocation.

**Typical fix:** Reduce the canvas size or the render DPI, or raise [budgets].max_surface_bytes in config.toml.

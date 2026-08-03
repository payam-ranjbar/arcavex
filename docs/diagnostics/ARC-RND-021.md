# ARC-RND-021 — Render surface exceeds the pixel budget

The render surface has more pixels than the per-render decoded-pixel budget allows (spec §8.3). Enforced from the canvas size and DPI before allocation, so a runaway surface cannot be created.

**Typical fix:** Reduce the canvas size or the render DPI, or raise [budgets].max_pixels in config.toml.

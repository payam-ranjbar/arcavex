# ARC-RND-020 — Output dimension exceeds the render budget

The render surface is wider or taller than the per-render output-dimension budget (spec §8.3). The limit is checked from the canvas size and DPI before any pixels are allocated, so an accidental runaway (a huge canvas, or a DPI override that multiplies it) is refused rather than exhausting memory.

**Typical fix:** Reduce the format's canvas size or the render DPI, or raise [budgets].max_dimension in config.toml.

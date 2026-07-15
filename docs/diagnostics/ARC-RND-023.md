# ARC-RND-023 — Render exceeded the wall-clock budget

The render took longer than the per-render wall-clock budget (spec §8.3). This is a post-hoc guard — Skia renders are not preemptible in v1 — so it flags a pathological render after it completes rather than interrupting it.

**Typical fix:** Simplify the scene or its effect chains, reduce the DPI, or raise [budgets].max_wall_ms in config.toml.

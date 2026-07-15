# Performance

Measured actuals against the spec §8.2 p95 targets. These numbers are produced by
`scripts/benchmark.py` — re-run it to reproduce them on your machine. Nothing here is estimated;
where a target is missed it is reported honestly with the real number and its cause.

## Reference machine

| | |
|---|---|
| OS | Windows 11 (10.0.26200) |
| CPU | AMD64, 24 logical cores |
| Python | 3.12.13 |
| skia-python | 144.0.post2 |

The spec's reference is an "8-core x86-64 or Apple-silicon laptop". This machine has more cores but
CI/ARM targets carry relaxed (2×) expectations (spec §8.2).

## Results

| Operation | Target (p95) | Median | p95 | Verdict |
|---|---|---|---|---|
| Template compile (event poster) | ≤ 50 ms | 13 ms | 16 ms | **pass** |
| Render 1080×1350, 3 raster effects | ≤ 1.5 s | 2.19 s | 2.40 s | **miss** |
| Render A4 @ 300 dpi, 4-deep effect chain | ≤ 6 s | 18.5 s | 18.6 s | **miss** |
| Peak RSS (A4 @ 300 render) | ≤ 1.5 GiB | 1.13 GiB | — | **pass** |
| CLI cold start to render-ready | ≤ 400 ms | 1.0 s | — | **miss** |

## Analysis of the misses

The misses are honest and all trace to costs that predate Phase 7 (this phase added exporters, the
derived cache, and resource budgets — none of which touch the effect or startup paths). They are
recorded here rather than hidden.

**Raster effects dominate the render numbers.** The *base* pipeline is well within budget: a plain
A4 @ 300 render (no effects) is ~0.8 s and a plain 1080×1350 is ~0.13 s. Each raster effect then
adds a large fixed cost — a full round-trip from the Skia surface to a NumPy array and back, plus
per-pixel work:

| 1080×1350 render | time |
|---|---|
| plain (no effects) | 0.13 s |
| + grain | 1.08 s |
| + noise | 1.00 s |
| + blur | 0.77 s |

So a 3-raster-effect 1080 scene lands at ~2.2 s and a 4-deep A4 @ 300 chain (6× the pixels) at
~18 s. The effects are already NumPy-vectorized; the dominant cost is the `skia.Image → ndarray →
skia.Image` conversion per effect at high pixel counts. Reducing it (operating on a shared mutable
buffer, or fusing consecutive raster passes the way color passes already fuse) is an effect-engine
optimization tracked in `docs/backlog.md`, out of scope for the export/release-hardening phase.

**Cold start is dominated by one-time imports.** The ~1 s cold start is import of `skia-python`
plus building the bundled-font database, both paid once per process. Long-lived processes — the MCP
server (`arcavex mcp`) and watch mode (`arcavex preview --watch`) — pay it a single time and then
render at the warm numbers above, which is the common agent-authoring loop. A short-lived
one-shot `arcavex render` pays it each invocation.

## What meets its target

Template compilation (13 ms p95 vs 50 ms) and peak memory (1.13 GiB vs 1.5 GiB, pooled surfaces
per spec §4.5) are comfortably inside budget, including for A4 @ 300 which is the memory-heavy case.
Determinism carries no measurable penalty — the byte-identical guarantee is structural, not a
runtime check.

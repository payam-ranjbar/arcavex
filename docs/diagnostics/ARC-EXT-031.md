# ARC-EXT-031 — Extension uses a non-deterministic API

A source file imports 'random', or a component method reads the wall clock or an undeclared file. Such use makes output depend on when or where it ran, so a rerun cannot reproduce the bytes (spec §3.2). This is a reproducibility rule, not a hostile-code check. The lint is a best-effort AST heuristic — it does not catch entropy hidden in a helper, behind an alias, or pulled in at import time — so a clean result is a reliability aid, not a guarantee.

**Typical fix:** Draw randomness from the seeded 'ctx.rng' (arcavex.sdk.effect_rng); do not read the clock or undeclared files in render-affecting code.

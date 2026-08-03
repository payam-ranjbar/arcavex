# Backlog — deferred and post-v1 items

Items explicitly deferred by the specification (§12, §7.4, Post-v1) or accepted as P3
during reviews. Nothing here is required v1 scope.

## Deferred by specification

- Hostile Python-extension isolation / WASM extension runtime (§7.4)
- GPU rendering backend (§4.5)
- Vector-preserving PDF, CMYK / PDF-X prepress (§4.6)
- Animation / video rendering (§1.3)
- Hosted service concerns: accounts, tenants, quotas (§8.3)
- SQLite discovery index (§5.4 — files remain canonical)
- Automatic installation of older engine versions for compatibility reruns (§12 open)
- Hyphenation (unless a concrete template requires it — none did in v1)

## Candidate: a narrow `audit` command (not committed)

From the readiness audit's P3-2. Validation checks that a design is well-formed, never whether it
is good — see
[known-limitations.md](known-limitations.md#validation-checks-geometry-not-design) for why that
boundary is deliberate. The only extension of it that would not compromise determinism is a
command limited to objective, testable checks:

- WCAG contrast per text node against its resolved backdrop
- minimum rendered cap-height at a declared viewing scale ("this 15px label is illegible in feed")
- declared safe-area assertions (`safe_area:` per format, machine-checked rather than
  hand-computed)
- optical-margin deviation between text left edges in one column

Anything beyond those four becomes opinion. Rough estimate ~1 week. Not scheduled, and not a
prerequisite for anything.

## Candidate: image preparation (P3-1 tier two, not committed)

`ARC-AST-020` (shipped) warns that an asset is mostly transparent padding. The two larger pieces
behind it are not built:

- **`fit: content-box`** — fit the opaque bounding box rather than the declared canvas, which
  removes the need to pre-trim at all. ~2 days.
- **`asset prep` subcommands** (`trim-alpha`, `chroma-key`, `focal-crop`) feeding the annotations
  `asset annotate` already accepts. ~1 week. The audit had to write both of these as throwaway
  scripts outside the engine to finish an ordinary poster.

## Landed in Phase 7 (was deferred)

- **Derived-variant asset cache (§4.7)** and **per-render resource budgets (§8.3)** — both shipped
  in Phase 7 (`services/cache/derived.py`, `services/budgets.py`). Kept here only as a pointer;
  see the ledger rows for §4.6/§4.7/§8.3.

## Open performance work (Phase 7 measured, not a v1 blocker)

- **Raster-effect render throughput (§8.2).** `docs/performance.md` records that the base
  pipeline is well inside budget (plain A4@300 ≈ 0.8 s, plain 1080×1350 ≈ 0.13 s, compile ≈ 15 ms,
  peak RSS ≈ 1.1 GiB) but effect-heavy scenes miss the p95 targets: each raster effect (grain,
  noise, blur) pays a full `skia.Image → ndarray → skia.Image` round-trip, so a 3-raster 1080
  scene is ≈ 2.2 s (target ≤ 1.5 s) and a 4-deep A4@300 chain is ≈ 18 s (target ≤ 6 s). The
  effects are already NumPy-vectorized; the fix is to operate on a shared mutable buffer and fuse
  consecutive raster passes the way color passes already fuse — an effect-engine optimization,
  out of scope for the export/release-hardening phase. Reported honestly rather than tuned to pass.
- **CLI cold start (§8.2).** ≈ 1 s to a render-ready engine (target ≤ 400 ms), dominated by the
  one-time `skia-python` import + font-database build. Long-lived processes (MCP server, watch
  mode) pay it once; a per-invocation `arcavex render` pays it each time. Amortizing it (lazy font
  DB, cached font index) is future work.

## Accepted P2 review findings

- **`set_data`/`import_data` validation is compile-only (CR-5).** `DataReport.diagnostics` are the
  project's compile diagnostics over the merged data (missing required variable, type mismatch,
  bad expression), located against the data file. They intentionally do **not** include the layout
  pass — that needs the render registries the orchestrator does not hold, and is not what a data
  edit conceptually validates — so a data change that overflows a box or overlaps a sibling is not
  reflected in the DataReport. An agent needing geometric feedback after a data edit calls
  `layout_inspect`/`render_preview`. The DataReport docstring states this honestly; wiring an
  optional layout check into the data path is deferred (it would duplicate the render wiring the
  facade already owns for `validate`/`layout inspect`).

## Accepted P3 review findings

- **Composite `backdrop` snapshot (CR-1).** `CompositeContext.backdrop` is a read-only accessor
  reserved for the content painted below a node in z-order (spec §3.2), but in v1 it always
  returns `None`: the renderer does not snapshot the underlying canvas region into it. No shipped
  behaviour depends on it — the two composite effects (drop-shadow, glow) build from the
  element's own alpha — so this is deferred rather than fixed in Phase 3. Populating it requires
  reading back the correct device-space region of the (possibly nested element) canvas under the
  full CTM and clipping it to the node's paint region; that is a renderer change larger than the
  latent gap warrants now. The docstring and the construction site state the deferral honestly so
  no future composite effect assumes a live backdrop.

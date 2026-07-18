# Arcavex v0.1.0 — Final Report (task §13)

Autonomous lead-engineer build executed against `arcavex-technical-design-spec-v1.1.md`
(the binding contract, copied at repo root). Full v1 scope delivered across 8 sequential
phases plus the flagship reference-poster reproduction, documentation set, and
clean-environment final verification. Date: 2026-07-17. Version: **0.1.0**.

## What was built

A local-first, headless, deterministic, template-driven rendering engine for posters and
social graphics on skia-python 144, CLI-first with an MCP server, organized as a strict
microkernel (`kernel` / `services` / `builtin` / `sdk` / `clients`, inward-only dependencies
enforced by import-linter, composition root in `bootstrap.py`).

| Phase | Delivered | Commits |
|---|---|---|
| −1 Scaffold + feasibility | Repo layout, spec contract, skia-python 144 feasibility spikes → ADR-0001 (SkParagraph-only shaping, ICU placement, RTL via BiDi isolates), pinned bundled fonts (Inter, Vazirmatn, Estedad, Lalezar + OFL) | `1193702` |
| 0 Kernel core | Typed IR, diagnostics model (code/severity/located source), registry, pipeline, direct render slice, hello-poster | `74f5d15` |
| 1 Authoring loop | Template compiler (variables, expressions, `repeat`/`if`, stable node IDs), units/colors, CLI render/validate, located errors | `1004936`, `b5ecdf8` |
| 2 Layout + text + locales | Constraint solver (anchors incl. logical start/end), stacks, SkParagraph text stack with fit policies, locales (direction/digits/fonts/data overlays → ADR-0002), masks, `layout inspect` | `157b799`…`0cb9d09` |
| 3 Effects + styles + goldens | Effect chains (15 builtin effects), seeded RNG tree, style packs, golden-image harness (DSSIM), pop-art grid | `0d051d7`, `223a33b` |
| 4 Projects + provenance | Projects, library (name@version), content-addressed assets + decode guards, run manifests, rerun/diff/batch, atomic writes | `599e249`, `5350d77` |
| 5 MCP surface | FastMCP stdio server, 24 tools mirroring the facade, agent session tests (P0 caught by DX review: Path coercion) | `eb50d77`, `6ba7fd7` |
| 6 Extension SDK | Trusted local extensions (honest no-sandbox trust model), `arcavex.sdk` public surface, loader, validator gates, GoldenHarness bounds-honesty, reference paper-texture extension | `9e02c15`, `9b11427` |
| 7 Export + release | JPEG/WebP/PDF exporters (A4 595.28×841.89 pt + Trim/BleedBox, no volatile metadata), derived-asset LRU cache (cold==warm identity), resource budgets → exit 4, packaged wheel install, CI workflow, v0.1.0 | `f5270ca`, `f9a90cd` |
| §9–10 Reference poster | `examples/reference-poster/`: split template, 5 formats × 2 locales, keyed-repeat guests in centred hstack, diamond-grid hero, circle portraits, two centred info blocks; 12 curated finals; design matrix 10/10 PASS | `81f2081`, `74223f1` |
| §12 Docs | Full documentation set: install, quick-start, template-schema, CLI, diagnostics (142 codes), architecture, tutorials ×3, contributing, known-limitations, ADR index; README showcase; ~40 doc commands executed for real transcripts | `858572f` |

## Final verification (task §11, clean environment)

| Gate | Result |
|---|---|
| `ruff check src tests` | clean |
| `mypy --strict src/arcavex/kernel` | clean (12 files) |
| `lint-imports` | 5/5 contracts kept |
| Full test suite (`pytest tests`) | **590 passed, 1 skipped (platform-gated), 0 failed** of 591 collected — unit, property, layout snapshots, golden, e2e, CLI, MCP sessions |
| CLI discovery | `--help` tree (10 commands + 9 groups) + `--version` → `arcavex 0.1.0` |
| MCP | 24 tools, `response_version: 1` |
| `doctor --json` | 9/9 checks ok |
| Packaged install | `uv build --wheel` → install into a **clean venv outside the dev tree** → doctor ok → renders |
| Reference poster (all 10 combos, clean venv) | exit 0 and **byte-identical to the committed finals** |
| Deterministic repeat (clean venv) | byte-identical |

Determinism is proven at its strongest available level: the same inputs produce the same
bytes across processes **and across install modes** (dev tree vs packaged wheel in a clean
venv), for PNG (all 10 poster combos) and — from Phase 7 verification — JPEG, WebP, and PDF.

## The reference poster (§9–10)

The supplied IPEN poster is reproduced as a reusable bilingual template rendered entirely by
the engine — no hand-compositing. 12 curated finals (10 PNG + 2 print PDF) in
`examples/reference-poster/outputs/final/`. A fresh-eyes visual design review scored **10/10
rows PASS, zero P1/P2** (`docs/agent-runs/reference-poster-design-matrix.md`); the single P3
(two-line venue, as in the reference) was applied. Operator feedback during the build shaped
the result: no blanket locale font override (it restyled always-English runs), exactly two
info blocks (date/venue, both centred), and cross-script-readable name/digit typography.
Acceptance is pinned by `tests/e2e/test_reference_poster.py` (renders, layout hygiene incl.
a content-collision rule, no clipped/truncated text, determinism, standalone preview data).

## Process

Agentic loop per phase: implement → code review → DX/design review → remediation →
orchestrator verification (re-review stage skipped from Phase 3 per operator directive;
model roles recorded in `docs/agent-runs/model-map.md`; all loop artifacts under
`docs/agent-runs/`). The dual-review design proved itself: Phase 5's DX review caught a P0
(MCP tools crashing on external data files) that both the code review and the test suite
missed. Session crashes occurred several times; per-phase checkpoint commits made every
resume lossless. Material decisions live in `docs/adr/` (2 ADRs);
`IMPLEMENTATION_LEDGER.md` tracks every spec section to its tests and acceptance evidence.

## Honest deviations and limitations

- Deferred by spec §12 (documented in `docs/known-limitations.md`): vector PDF, CMYK/PDF-X,
  GPU, WASM/untrusted-extension sandbox, animation, hosted concerns.
- Extensions are **trusted local code** — integrity gates (import-surface scan, determinism
  lint, bounds honesty), explicitly **no** security sandbox claim (spec §7.3).
- Performance: measured actuals in `docs/performance.md`; two §8.2 targets missed and
  disclosed (raster-effect throughput on the A4 deep chain; CLI cold start) rather than faked.
- Platform: built and verified on Windows (win-amd64); per-platform goldens + the
  linux/macos CI matrix ship configured but were not run locally (`docs/testing.md`).
- `skia-python` 144 lacks `setTextDirection`; RTL uses Unicode BiDi isolates (ADR-0001) —
  caveats documented.
- Layout-inspect reports AABB overlaps for the poster's rotated band accent that are
  visually clear; the e2e test encodes the precise allowed set instead of ignoring overlaps.

## Repo statistics

455 tracked files; 89 source modules (~24.5k lines) + 64 test modules (~9.7k lines);
142 documented diagnostic codes; 15 builtin effects; 8 SPI contracts; 24 MCP tools;
14 bundled font files; 22 commits, every phase checkpointed.

## Status

**v0.1.0 release gate: met.** All phases accepted, reference poster accepted, docs complete,
final verification green. The repository is local-only by operator directive
("don't push until I say it") — pushing to `github.com/payam-ranjbar/arcavex` (private)
awaits explicit approval and will be the single remaining step.

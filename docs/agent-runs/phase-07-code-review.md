# Phase 07 code review — Export & release hardening (v0.1 release gate)

**Commit reviewed:** `f5270ca` (diff base `9b11427`)
**Reviewer:** adversarial Opus review, read-only for production code/tests
**Date:** 2026-07-15
**Verdict:** **APPROVE with minor fixes.** Every Phase 7 exit criterion is met and independently
verified by execution. The release-gate guarantee — byte-identical output across PNG/JPEG/WebP/PDF —
holds under cross-process re-render. No P0/P1 determinism or release-gate break was found. Two P2
findings (a fabricated packaged-install transcript, an unbounded derived-cache disk tier) and a
handful of P3 notes should be cleaned up before tagging 0.1.0 but do not compromise the core
guarantees.

---

## Gates (executed on this machine)

| Gate | Result |
|---|---|
| `pytest tests -q` | **563 passed, 1 skipped, 0 failed** (exit 0) |
| Skip reason | `tests/unit/test_file_safety.py:70` — symlink creation not permitted on this Windows account (env-gated, legitimate) |
| `ruff check src tests` | **All checks passed** |
| `mypy src/arcavex/kernel --strict` | **Success, no issues** (12 files) |
| `lint-imports` | **5 contracts kept, 0 broken** (kernel purity intact) |

The one skip is environmental: the `..`-traversal test runs and passes, and the symlink path uses
the same `_is_within(resolved, root)` check on a `.resolve()`d path, so the guard logic is exercised;
only the symlink-specific assertion is skipped on Windows (it runs on POSIX CI).

## Determinism — the release gate (verified by execution, cross-process)

Rendered each format **twice in separate `arcavex.exe` invocations** and compared SHA-256:

| Format | Command | Re-render byte-identical? |
|---|---|---|
| JPEG (`--quality 100`) | hello-poster square | ✅ `03ff2100…` == `03ff2100…` |
| WebP | hello-poster square | ✅ `e5d8f245…` == `e5d8f245…` |
| PDF (A4, fa, RTL raster) | ipen-bilingual a4 | ✅ `42579356…` == `42579356…` |
| PNG (regression) | hello-poster square | ✅ `91f91c93…` == `91f91c93…` |
| PNG (regression) | pop-art-grid square | ✅ `d3146145…` == `d3146145…` |

**PDF volatile-metadata audit** (grep of `ipen1.pdf` bytes): `/CreationDate` **0**, `/ModDate` **0**,
`/ID` **0**. Only stable metadata present: `/Producer (Arcavex 0.1.0)`, `/Creator (Arcavex 0.1.0)`,
`/Title (color:sRGB)`, `/Subject (render:056486…)`. Skia's default PDF date/ID leakage **is
neutralized** — the box-rewriter rebuilds the trailer with only `/Size`, `/Root`, `/Info` (no `/ID`),
and `PDF.Metadata` leaves creation/mod timestamps unset. This is the single biggest determinism risk
for the phase and it is correctly handled.

## PDF physical size + bleed (verified)

- **A4 no-bleed** (ipen a4): MediaBox = TrimBox = BleedBox = `[0 0 595.275591 841.889764]` = exact A4.
- **A4 + 3 mm bleed** (synthetic template, dpi 150): MediaBox `[0 0 612.283 858.898]` (216×303 mm),
  TrimBox `[8.504 8.504 603.780 850.394]` (3 mm inset, 210×297 mm trim), BleedBox = MediaBox (v1
  policy: bleed spans full media). All exactly as spec §4.6/§3.1.2 require.
- **Real-reader validity:** both PDFs open in **PDFium (pypdfium2)** — 1 page, sizes 595.28×841.89 and
  612.28×858.90 pt. The hand-rolled xref rewrite (`export_pdf/boxes.py`) produces valid PDFs a real
  reader accepts, not just bytes that pass the self-test regex.

## Exporters, cache, budgets, safety (assessed)

- **Exporter selection** by extension (`.png/.jpg/.jpeg/.webp/.pdf`) resolves via the registry
  (`_EXPORTER_BY_EXT` → `registries.exporters.get`); all four registered as built-ins on the
  `Exporter` contract in `bootstrap.build_registries`. Unsupported extension → `ARC-EXP-011`, exit 1,
  no file written (e2e verified). JPEG/WebP quality + WebP lossless honored (`test_export_formats`,
  `test_export_cli` pass; lossless WebP proven bit-exact by round-trip).
- **Derived cache** (`services/cache/derived.py`): keyed by `(sha256, target_w, target_h)`;
  cold==warm byte-identity verified (`test_render_is_identical_cold_vs_warm`, two independent cold
  homes agree); disposable (delete → identical render); config via `[cache].derived_bytes`. **In-memory
  LRU eviction under byte budget works** (verified). See CR-2 for the disk-tier gap.
- **Budgets** (`services/budgets.py`): dimension/pixel/surface-memory checked pre-allocation, wall-clock
  post-hoc; each raises a located `ARC-RND-020..023`; CLI maps them to **exit 4** (e2e:
  `test_oversized_render_exits_with_budget_code` → returncode 4, `ARC-RND-020`, no file). Located on the
  template canvas keypath.
- **Atomic writes / interruption:** every output writer (`export_raster/encode.py`, `export_pdf/pdf.py`,
  cache `_write_disk`) routes through `fsutil.atomic_write_bytes` (temp beside target + `os.replace`,
  temp unlinked in `finally`). Interrupted-write test (monkeypatched `os.replace` raising) leaves the
  prior file intact and no `.tmp` residue. (Note: no `fsync` before replace — a durability, not
  atomicity, gap; acceptable for v1.)
- **File safety** (`test_file_safety`): `../` traversal and malformed-asset (`ARC-AST-002`, no partial
  output) both real and passing; symlink test env-skipped here.
- **Doctor** covers exporters (encodes a tiny surface through PNG/JPEG/WebP + builds a PDF), cache
  (dir + resolved budget), and ICU (`skia.Unicode()` probe with the ADR-0001 remediation hint).
  `doctor --json` emits real JSON.
- **§12 lock respected:** no vector-PDF, CMYK/PDF-X, GPU, or WASM code — only doc comments marking them
  future work. Raster-embedded RGB PDF only.

---

## Findings

### CR-1 (P2) — Packaged-install transcript is hand-authored, presented as captured
`docs/packaged-install.md` shows a transcript "captured on the Phase 7 development machine" in which
`$ arcavex doctor --json` prints a **human-readable table** (`engine 0.1.0 ok True / python ok Python
3.12.13 / …`). The real `doctor --json` emits JSON (`{"response_version": 1, "ok": true, …}`), verified
by execution. The transcript is therefore fabricated/illustrative, not captured — the brief explicitly
asked to confirm it is "real not aspirational". The doc's byte-identical claim ("installed engine's
`hello.png` is byte-identical to the dev-tree render") is also not backed by any in-repo test.
*Fix:* regenerate the transcript from real output (or drop `--json` from the shown command / show real
JSON), and either add a test asserting installed==dev SHA or soften the claim. The underlying
functionality is fine — the orchestrator's real clean-venv install was independently confirmed; this is
a documentation-honesty defect on a release doc.

### CR-2 (P2) — Derived-cache disk tier has no eviction (byte budget bounds memory only)
`DerivedImageCache` enforces `byte_budget` only on the in-memory `OrderedDict` (`_admit`, lines
107–110). `_write_disk` writes variant PNGs to `$ARCAVEX_HOME/cache/derived/` with **no size accounting
and no LRU pruning**, so the disk tier grows unbounded across distinct `(hash,size)` variants. The
module docstring states "both tiers are disposable and **evicted least-recently-used when over budget**"
and `_read_disk` calls `os.utime(..)` "for disk-LRU recency" — implying a disk LRU that does not exist.
Spec §4.7 asks for byte-budget LRU eviction. Impact is bounded (the cache is genuinely disposable —
delete → identical render, verified) but the stated guarantee is only half-implemented.
*Fix:* enforce the byte budget on disk (sweep by mtime when over budget), or correct the docstring to
say the disk tier is unbounded and manually disposable. If the reviewer's bar treats §4.7's byte budget
as covering the persistent tier, escalate to P1.

### CR-3 (P3) — CI installs `pypdfium2` but nothing uses it
`.github/workflows/ci.yml` packaged-install job runs `uv pip install … dist/*.whl pypdfium2`, but the
render step outputs PNG and no test imports pypdfium2 (grep: only ci.yml references it). Dead CI
dependency — either add a `pypdfium2`-based PDF-open validation to the job or drop it.

### CR-4 (P3) — Performance misses are large but honestly disclosed
`docs/performance.md` reports three missed p95 targets: 1080×1350 3-effect **2.40 s** (target 1.5 s),
A4@300 4-deep **18.6 s** (target 6 s — 3× over), CLI cold start **1.0 s** (target 400 ms). All are
honestly measured by `scripts/benchmark.py` (a real, runnable harness) and correctly attributed to
pre-Phase-7 costs (per-effect `skia→ndarray→skia` roundtrip; one-time skia import + font DB build) —
none introduced by this phase, which doesn't touch the effect or startup paths. **I agree with the
honesty.** Flagging only that the A4 miss is sizeable for a "release gate"; perf targets are explicitly
not a hard gate per the brief, so no code change is required.

### CR-5 (P3) — Cache-vs-no-cache is "~1:1", not pixel-exact, for cover/contain
For `cover`/`contain` fits the cache downscales to a fitted box which `drawImageRect` then resamples
again (two resamples vs one on the no-cache path), so **enabling vs disabling** the cache can shift
pixels for large cover/contain images. This does **not** affect the release gate: the cache is always
wired in production, cold==warm is byte-identical, and all golden tests pass (the example scenes don't
trip the 4 MP / 4× threshold). `_target_pixels` honestly says "~1:1", but the top-of-module docstring's
"None (no cache) renders the same pixels" reads as exact. Low risk; note for accuracy.

### Note — symlink-traversal coverage is POSIX-only
The symlink assertion skips on this Windows account (no privilege). The containment guard itself is
sound and shared with the `..` path; ensure CI (Linux) exercises the symlink case.

---

## Reproduction commands

```powershell
.venv\Scripts\python.exe -m pytest tests -q                 # 563 passed, 1 skipped
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m mypy src/arcavex/kernel --strict
.venv\Scripts\lint-imports.exe
# determinism (run each twice, compare sha256): .jpg .webp .pdf .png  -> all byte-identical
# PDF metadata: grep bytes for /CreationDate /ModDate /ID  -> 0 occurrences
# bleed: render A4+3mm template -> MediaBox 612.28x858.90, TrimBox inset 8.504 (=3mm)
# pypdfium2 opens both PDFs (1 page, correct pt size)
```

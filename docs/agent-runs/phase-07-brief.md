# Phase 07 brief — Export and release hardening (spec §11 Phase 7, §4.6)

## Scope

1. **Full exporters** (§4.6): complete the Exporter contract implementations —
   - PNG (exists), JPEG (quality in ExportOptions), WebP (quality/lossless) — via
     builtin/export_raster/. Format chosen by output extension or explicit --format-out/opts.
   - PDF: raster-embedded RGB at target DPI with CORRECT physical page size and bleed boxes
     (§4.6, §3.1.2 — A4 210×297mm + bleed must be first-class). Vector PDF and CMYK/PDF-X stay
     deferred (§12). builtin/export_pdf/. Exported files carry only STABLE metadata (engine
     version, render signature, color profile, content hash) — NO timestamps/run ids (identical
     reruns byte-identical). Verify JPEG/WebP/PDF determinism too.
   - CLI: `-o out.jpg` / `.webp` / `.pdf` selects the exporter by extension; export options
     (quality, lossless, dpi) surfaced. render_file returns the right report per format.
2. **Derived asset cache** (§4.7): the deferred LRU downscale cache — variants keyed by
   (hash, params) under a byte budget, so a 40MP photo into a 400px slot decodes/downscales
   once. Under $ARCAVEX_HOME/cache/, disposable, LRU eviction by byte budget (configurable via
   config.toml per §6.3). Cache is never authoritative; a cold cache produces identical output.
3. **Cache + resource budgets** (§8.3): per-render wall-clock, decoded-pixel, surface-memory,
   and output-dimension budgets enforced with located diagnostics (ARC-RND budget) + exit 4.
   Decode guards already exist (Phase 4) — ensure they cover the new exporters' inputs.
4. **Atomic writes + interruption** (§8.3): all output writes atomic (temp+rename — audit every
   writer); a cancelled/interrupted render publishes NO partial output (temp cleaned up); test
   an interrupted render leaves only the pre-existing state. Immutable completed run dirs.
5. **Performance** (§8.2): measure against the p95 targets on this machine and RECORD actuals in
   the report + a docs/performance.md — template compile ≤50ms, render 1080×1350 ≤3 raster
   effects ≤1.5s, A4@300 4-deep chain ≤6s, peak RSS ≤1.5GB, CLI cold start ≤400ms. Where a
   target isn't met, note it honestly (don't fake); add a lightweight benchmark harness
   (pytest-benchmark optional or a timed script) that can be re-run.
6. **Packaged installation test** (§8.5): build the wheel (`uv build` or python -m build), install
   it into a CLEAN throwaway venv, and run the documented quick-start commands from that install
   (arcavex render examples/... ) — proving the package ships fonts + icu data + works without the
   dev tree. Document the icudtl.dat handling for installed use (ADR-0001) — the wheel/doctor must
   make ICU work or diagnose it. Add a test or scripted transcript.
7. **linux-aarch64 CI note** (§8.5): CI matrix is out of local scope, but document the intended
   matrix (linux-x86_64 + macos-arm64 + linux-aarch64) and the golden per-platform strategy in
   docs/testing.md or CONTRIBUTING; provide a GitHub Actions workflow file (.github/workflows/
   ci.yml) that runs lint+typecheck+tests+goldens (it won't run locally but ships correct).
8. **Release hardening**: version bump to 0.1.0 (from 0.1.0.dev0) readiness; CHANGELOG.md
   generated/curated; `arcavex doctor` covers the new exporters + cache + ICU; ensure --version,
   exit codes, JSON schemas are stable (snapshot tests per §9).
9. **Tests**: JPEG/WebP/PDF export + determinism + physical-size (PDF page mm) tests; cache
   hit/miss + eviction + cold==warm output identity; budget enforcement (oversized render →
   exit 4 located); interrupted-write atomicity + malformed-asset + path-traversal (the §8.5
   file_safety suite); packaged-install transcript; perf benchmark script; golden updates for
   any new visual output.

## Carry-over
Open P3s from phase-06 reviews (check reports). None expected to block.

## Non-goals
Vector PDF, CMYK/PDF-X (§12 deferred). GPU. WASM. Animation. Hosted concerns. Do NOT add a
prepress pipeline — raster-embedded RGB PDF only.

## Constraints
- Determinism extends to ALL formats: same inputs → byte-identical JPEG/WebP/PDF (no embedded
  timestamps; libjpeg/libwebp/skia PDF must be invoked deterministically — verify + test).
- Exporters resolve via registry; PDF/JPEG/WebP are built-ins obeying the Exporter contract.
- Cache/budgets configurable via the §6.3 config chain; cache disposable.
- Kernel pure; all existing tests green; new codes documented.

## Acceptance commands
```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\arcavex.exe render examples/hello-poster/template.yaml --data examples/hello-poster/data.yaml --format square -o outputs-tmp/out.jpg
.venv\Scripts\arcavex.exe render examples/hello-poster/template.yaml --data examples/hello-poster/data.yaml --format square -o outputs-tmp/out.webp
.venv\Scripts\arcavex.exe render examples/ipen-bilingual/template.yaml --data examples/ipen-bilingual/data.yaml --format a4 --locale fa -o outputs-tmp/ipen.pdf
.venv\Scripts\arcavex.exe doctor --json
# packaged install: build wheel, install in clean venv, run quick-start
```

## Exit criteria (spec Phase 7)
JPEG/WebP/PDF export with correct physical sizing + determinism; derived cache with cold==warm
identity + LRU eviction; resource budgets enforced with located diagnostics; atomic writes +
clean interruption; performance targets measured + recorded; packaged install works from a
clean venv; CI workflow + per-platform golden strategy documented. This is the v0.1 release gate.

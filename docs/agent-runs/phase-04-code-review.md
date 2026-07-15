# Phase 04 code review — Projects and provenance

**Reviewer:** adversarial code review (read-only for production code/tests)
**Target:** commit `599e249` (diff base `223a33b`), Windows / `.venv`
**Date:** 2026-07-14

## Verdict

**Accept with required fixes (one P1 cluster + one P2).**

The determinism headline — the whole point of this phase — **holds under execution**: same-platform
rerun is byte-identical (including after the source data file is edited), batch parallel is
byte-identical to serial, canonical hashing resolves CR-13, exported PNGs carry no timestamp, and
concurrent run directories are unique. Gates are all green. What is missing is **provenance
completeness for the project-patch input**: the patch (the PROJECT layer in the resolution order) is
never captured in the manifest by hash, so `diff` cannot explain a patch-driven change and there is
no changed-on-disk detection before a patch is applied on rerun. The byte-comparison in rerun
prevents this from becoming a *determinism* failure, but three explicitly-required Phase 4 behaviors
(item 4 "every input by hash", item 6 diff attribution, item 10 §8.3 changed-on-disk) are incomplete.

## Gates (all pass)

| Gate | Command | Result |
|------|---------|--------|
| Tests | `pytest tests -q` | **355 passed** |
| Lint | `ruff check src tests` | clean |
| Types | `mypy src/arcavex/kernel --strict` | Success, 12 files |
| Imports | `importlinter.cli lint` | clean |

## Determinism verification (by execution)

Isolated `ARCAVEX_HOME` under `outputs-tmp/review4/home`; template `examples/hello-poster` published
as `poster@1.0.0`.

- **Rerun byte-identity** — `arcavex rerun outputs/<run>`: both outputs' sha256 identical to source;
  `reproduction.json` `reproduced:true`, `engine_match/platform_match:true`.
- **Rerun after editing the data file** — rewrote `data/ipen.yaml` to a totally different title, then
  reran the *original* run: output bytes still identical to the original (reproduces from the manifest
  snapshot, not the edited file). ✅ Correct.
- **Rerun after editing the project patch** — rendered run P with a green-background patch, edited the
  patch on disk to blue, reran P: rerun **detected** the drift (`reproduced:false`,
  `mismatched_outputs:[both]`). Not silent (byte comparison catches it) — but see CR-1 for what it
  *cannot* tell the user.
- **Batch serial == parallel** — 3 projects (alpha/beta/gamma), `--jobs 1` vs `--jobs 4`: all 6
  output sha256 **identical**. Parallelism is process-based (`ProcessPoolExecutor`, `pool.map` preserves
  input order); no intra-job parallelism; distinct run dirs.
- **Concurrent run-dir uniqueness** — `RunStore.new_run_dir` called 4× with the same base id →
  `id, id_2, id_3, id_4` (atomic `os.mkdir`, no clobber). ✅
- **PNG timestamp-free** — fresh (non-rerun) render 3 minutes later: byte-identical to the earlier
  render; only the injected clock (`runs.utc_now`, the sole `datetime.now` in the render path) varies
  the surrounding run id.
- **Canonical CR-13** — `hash(2)==hash(2.0)`, `hash(2)!=hash("2")`, `hash(True)!=hash(1)`, key-reorder
  stable; property + unit tests pass. Serializer is genuinely shared: template hash, style hash, data
  hash, manifest fingerprint, font hash, and diff data hash all route through `kernel.ir.canonical`.
- **Decode guards** — junk bytes → `ARC-AST-002`; a 49-byte file whose PNG header claims 100000×100000
  px → `ARC-AST-003` fired **before decode** (header-only probe). ✅ §4.7 satisfied.
- **Library immutability** — republish `poster@1.0.0` → `ARC-LIB-002`; version dir untouched.
- **Upgrade stale-path** — published `poster@2.0.0` renaming node `background`→`bg`; a project pinned
  to 1.0.0 with a patch on `background`: `project upgrade --to 2.0.0` reports the stale patch path and
  does **not** mutate the pin; `--yes` pins it. ✅
- **Architecture** — kernel imports no service/builtin/client (grep clean); facade wraps every
  orchestrator call in `_guard_project` (catches `DiagnosticError` and any `Exception`), never raises;
  no global active-project state (only a process-local worker-facade cache in bootstrap); every emitted
  diagnostic code is documented and mirrored (`test_every_emitted_code_is_documented`,
  `test_docs_diagnostics_mirror_catalog`).

## Findings

### CR-1 [P1] — Project patch is not a hashed manifest input; diff can't attribute it; no changed-on-disk detection

The project override patch (`overrides/<template>.patch.yaml`) is the **PROJECT layer** in the
resolution order (style→template→format→locale→**project**, §5.4) and materially affects output. It is
**never captured in the manifest**: `RunManifest` records `template`, `style`, `assets`, `fonts`, data
snapshot, seed, options — but no patch hash. On rerun the patch is re-read fresh from disk
(`orchestrator._reload_project_patch`) with no comparison to what the recorded run used.

Consequences (three required behaviors affected):

1. **Manifest incompleteness** (brief item 4 / exit criterion "manifests capture every input by hash"):
   the patch is the one resolution input with no hash.
2. **Diff cannot attribute a patch change** (brief item 6 / §5.3). Demonstrated: two runs of one project
   differing **only** by the patch (green vs blue background):
   ```
   arcavex diff <green-run> <blue-run>
   → ipen.square.png: dssim 0.2741
   → ipen.story.png:  dssim 0.2731
   → no metadata changes
   ```
   A 0.27 DSSIM visual difference reported with **"no metadata changes"** — diff shows *what* differs but
   nothing about *why*, defeating its stated purpose.
3. **No changed-on-disk detection before applying a patch** (§8.3 / brief item 10). Rerun silently
   re-reads the edited patch; only the output-byte comparison flags drift (`reproduced:false`), and it
   cannot say the patch was the cause.

Not a determinism failure — the rerun byte comparison protects the `reproduced` flag — but it violates
the manifest/diff/safety requirements above.

**Fix:** canonicalize+hash the applied project-patch ops into the manifest (e.g. a `patch: InputRef`);
add it to `_diff_metadata`; on rerun compare it (and the recomputed template hash) to the manifest and
surface a patch/template-drift reason.

**Files:** `services/runs.py` (`RunManifest`, `_diff_metadata`), `services/orchestrator.py`
(`_finalize`, `rerun`, `_reload_project_patch`).

### CR-2 [P2] — `diff` metadata omits asset changes

`runs._diff_metadata` compares template, template.hash, style, engine_version, platform, ir_version,
dpi, fonts, and per-locale data — but **not assets**, even though the manifest records `assets` by
sha256. Brief item 6 explicitly requires reporting **asset** changes separately. An asset-only change
(a referenced image's bytes swapped) is therefore unattributed in the metadata delta.

**Fix:** add an assets comparison to `_diff_metadata` (e.g. compare a combined hash of the sorted
per-asset sha256s, and/or list added/removed/changed asset paths). **File:** `services/runs.py`.

### CR-3 [P3] — reproduction report can't explain a failed reproduction

`reproduction.json` records `engine_match`, `platform_match`, and `mismatched_outputs`, but when both
match and outputs still differ (a template/patch/asset changed on disk) the user gets no input-drift
reason. Same root cause as CR-1: rerun does not re-verify the recomputed input hashes against the
manifest. **Fix:** on rerun, compare recomputed template/style/data/patch/asset hashes to the manifest
and record which drifted. **File:** `services/orchestrator.py` (`rerun`, `_write_reproduction`).

### Note (not a finding) — canonical numbers above 1e15

`_canonical_number` keeps integral floats `≥1e15` as floats, so `1e16` (float, → `1e+16`) and `10**16`
(int, → `10000000000000000`) hash differently. Documented, intentional (int↔float round-trip is no
longer exact there), and unrealistic for template inputs. No action.

## Scrutiny pointers from the implementer's report (verified)

- `orchestrator._reload_project_patch` / `_resolve_manifest_template` — confirmed the patch is re-read
  from disk and not hashed in the manifest → **CR-1**. Library templates are immutable (safe); path
  templates re-read from disk but their hash *is* in the manifest (diff can catch it — unlike the patch).
- `compiler._build_context` rerun early-return skipping re-validation — **intended and safe**: the
  snapshot was validated at record time; re-running validation would re-emit coercion warnings.
- `runs.short_hash` inputs-only — confirmed (template/style/dpi/targets/data_hash, not the clock); two
  identical-input renders share the fingerprint and differ only by timestamp. Correct.
- `probe.py` WEBP best-effort — header-only VP8/VP8L/VP8X parsing; guards enforced pre-decode. Correct.

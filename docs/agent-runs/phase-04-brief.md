# Phase 04 brief — Projects and provenance (spec §11 Phase 4)

## Scope

1. **Project model** (§5.2): `project.yaml` manifest (name, template ref, style, locales,
   formats, data path, status draft|review|approved|published, tags). Project layout:
   data/, assets/, overrides/<template>.patch.yaml, outputs/<run>/. Facade:
   create_project, list_projects, project_status, clone_project, set_project_status.
   `arcavex project new NAME --template REF` scaffolds a real project that renders; upward
   `project.yaml` discovery (resolve_project walking up from cwd); `--project PATH` override;
   NO global "active project" state (concurrent-safe).
2. **Versioned local library** (§5.1, §5.5): `$ARCAVEX_HOME/templates/<name>/<version>/` +
   index.toml (versions + optional default alias); `arcavex template publish` writes an
   immutable version dir; projects pin `name@version`; bare name only if index declares a
   default (never silent "latest" in a recorded render). Styles library reading already
   exists (Phase 3) — align. library-seed/ is the shipped seed; a project can reference
   library templates by name@version.
3. **Canonical hashing for provenance** (§3.1.4, and the CR-13 float-form ticket — RESOLVE IT
   HERE): canonical serializer with NFC strings, units normalized to pt, sorted keys, stable
   list order, normalized numeric repr (unify int/float text form so 2 and 2.0 hash equal per
   spec intent — fix the phase-1 CR-13 deviation and its test), no absolute paths. Shared by
   template/style/data hashing, manifests, and cache keys. Property test: stable across
   re-serialization and key reordering.
4. **Run manifests** (§5.3): project render + direct render with `--record` write
   outputs/<timestamp>_<shorthash>/manifest.json capturing engine version, platform, IR
   version, canonical template/style/data hashes, resolved data snapshot, asset+font hashes,
   seed, options, diagnostics, timings, output file hashes. Exported PNGs contain NO timestamp
   or run id (already true — verify). Manifest timestamp uses a passed-in clock, never
   embedded in image bytes.
5. **Deterministic rerun** (§5.3): `arcavex rerun outputs/<run>` uses the recorded resolved
   snapshot + stable metadata, creates a NEW run dir + reproduction report; output bytes MUST
   match on same engine version + platform (the headline exit criterion). If engine version
   differs, refuse exact-repro claim and optionally do a labeled compatibility render.
6. **Diff** (§5.3): `arcavex diff outputs/<a> outputs/<b>` reports (a) per-output pixel/
   perceptual difference (reuse the SSIM harness) and (b) separately: template, data, asset,
   font, engine, option changes (from manifests). JSON + human.
7. **Batch rendering** (§6.1.2): `arcavex batch <projects-glob> --jobs N` renders formats×
   locales across projects; parallel MUST be output-identical to serial (jobs independent, no
   intra-job parallelism); deterministic. `render_project(project, formats, locales, dpi)`,
   list_runs, batch_render.
8. **Project patches** (§5.4): overrides/<template>.patch.yaml applied as the project layer in
   resolution order (style → template → format → locale → PROJECT). Detached templates via
   `arcavex template detach` (copies library template into project, warns upgrades disabled).
9. **Upgrade previews** (§5.5): `arcavex project upgrade --to VERSION` compiles old+target over
   current data, reports patch paths that no longer resolve, renders comparable previews,
   shows structural + perceptual diff, updates the pin only on explicit acceptance (a --yes or
   interactive confirm; for autonomous use provide --yes and default to NOT mutating).
10. **Safety** (§8.3): atomic writes (temp+rename), immutable completed run dirs, unique run
    dirs for concurrent renders, atomic CAS insertion, lock-protected template publication +
    library index updates. Changed-on-disk detection before applying a patch.
11. **Tests**: project create/discover/status/clone; publish→pin→render; rerun byte-identity
    (same platform) — the key test; diff (pixel + metadata) ; batch serial==parallel identity;
    project patch layer + provenance; upgrade stale-path detection; canonical hash property
    tests incl. the CR-13 fix; concurrency (two renders → distinct run dirs, no clobber);
    manifest completeness; CLI transcripts.

## Carry-over
CR-13 canonical float unification (listed above, item 3) is due this phase.

## Non-goals
MCP (Phase 5), extension SDK (6), JPEG/WebP/PDF + cache budgets (7). Asset CAS is needed
enough for manifests (asset hashes) — implement a minimal CAS in services/assets/ now if not
present (ingest-by-sha256, sidecar mime/dims); full derived cache + decode-guard hardening is
Phase 7, but decode guards (max pixels/bytes) should exist minimally here since assets are
ingested. Coordinate: if §4.7 asset system is easier to do fully now, do the CAS+sidecars+
decode-guards part and leave derived-cache LRU for Phase 7 (note the split).

## Constraints
Files canonical, indexes/caches disposable (§5.4). No network. Kernel pure. Determinism is the
whole point of this phase — hold the line. All existing tests green; new codes documented.

## Acceptance commands
```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\arcavex.exe project new outputs-tmp/proj/ipen --template <seeded-lib-template-or-path>
.venv\Scripts\arcavex.exe render   # inside the project dir (discovers project.yaml)
.venv\Scripts\arcavex.exe list-runs # or `arcavex runs` — use the implemented name, keep README synced
.venv\Scripts\arcavex.exe rerun outputs/<run>
.venv\Scripts\arcavex.exe diff outputs/<run-a> outputs/<run-b>
.venv\Scripts\arcavex.exe batch outputs-tmp/proj/* --jobs 4
```

## Exit criteria (spec Phase 4)
Same-platform rerun is byte-identical; project upgrade detects stale patch paths; batch
parallel == serial; manifests capture every input by hash; canonical hashing stable.

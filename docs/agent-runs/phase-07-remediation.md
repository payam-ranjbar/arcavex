# Phase 07 remediation — Export & release hardening (v0.1 release gate)

**Base commit reviewed:** `f5270ca` · **Remediation date:** 2026-07-15 · **Engine:** 0.1.0
**Reviews addressed:** `phase-07-code-review.md` (CR-1..CR-5), `phase-07-dx-design-review.md` (DX-1..DX-6)

All P1 and P2 findings are fixed at the root cause; both discretionary P3s (CR-3, CR-5) are also
resolved. Format determinism is preserved — every format re-renders byte-identically across
processes (re-verified below). No test or acceptance criterion was weakened.

## Finding → action → test

| # | Sev | Finding | Root-cause action | Test |
|---|-----|---------|-------------------|------|
| DX-2 | P1 | Unwritable output path leaked as `ARC-INT-999`/exit 5; `ARC-EXP-001` registered but never raised | Wrapped the `mkdir` + `exporter.export` write in `_render_file_inner` in a targeted `except OSError` → located `ARC-EXP-001` (names the path, hint "check the output path is writable / parent exists"), exit 1 (validation/authoring error, §6.1.3). | `test_export_cli.py::test_unwritable_output_path_raises_located_export_error` (render to a path whose parent is a file → exit 1, `ARC-EXP-001`, not `ARC-INT-999`) + `test_explain.py::test_registered_codes_are_reachable` (every registered code has a raise-site or a documented exemption) |
| DX-1 | P1 | `doctor` reported two contradictory home dirs (`paths` used OS-temp, `cache` used `home_dir()`) | `_check_paths()` now resolves through `fsutil.home_dir()` — the single source of truth the cache check and library already use. | `test_doctor.py::test_doctor_paths_and_cache_agree_on_home`, `::test_doctor_paths_follows_arcavex_home` |
| CR-1 | P2 | `docs/packaged-install.md` had a **fabricated** transcript (`doctor --json` shown printing a human table) | Regenerated the **entire** transcript from real output: `uv build --wheel`, clean `uv venv`, wheel install, `doctor`, `doctor --json` (real JSON), both quick-start renders. Byte-identity claim now cites the real SHA-256 and attributes the guarantee to the cross-process determinism tests (no fabricated dedicated test). | (doc) backed by `test_export_formats.py` / `test_derived_cache.py` cross-process determinism + `test_packaged_install.py` (wheel bundles fonts) |
| CR-2 | P2 | Derived-cache **disk** tier had no eviction; docstring claimed both tiers evict LRU | Implemented real disk LRU eviction: after each write, `_prune_disk()` sweeps `cache/derived/` and deletes oldest-by-mtime until under the byte budget. Read-hits `os.utime` the file, so recency drives survival. Cold==warm identity unchanged (re-derivation is deterministic). | `test_derived_cache.py::test_disk_tier_evicts_under_byte_budget` |
| DX-4 | P2 | JPEG default quality 100 → files larger than PNG, no visible gain | Default lossy quality (JPEG + lossy WebP) lowered to **90** (`_DEFAULT_EXPORT_QUALITY`, `ExportOptions.quality`); `--quality` help + README now state the default. hello-poster JPEG dropped 71,707 → 39,202 bytes; still deterministic. No JPEG goldens exist (goldens are PNG), so none needed regenerating. | existing `test_export_formats.py` / `test_export_cli.py` (explicit quality) + determinism re-verify |
| DX-3 | P2 | PDF `bleed:` canvas field worked but was undocumented | README `formats:` section now documents `bleed: <dim>` (MediaBox/BleedBox grow past TrimBox; A4+bleed in one command) and states PDF is raster-embedded RGB, not vector/CMYK. | (doc) `test_export_formats.py::test_pdf_physical_size_and_bleed_boxes` already asserts the mechanism |
| DX-5 | P3 | README "Known limitations" still called the derived cache "deferred" | Rewrote the bullet: the cache shipped this build under `$ARCAVEX_HOME/cache/derived/`; points at the new config table and `doctor`. | — (doc) |
| DX-6 | P3 | `[budgets]`/`[cache]` config keys undocumented despite diagnostics telling users to edit them | Added a config-key table to README's precedence section (`max_dimension`/`max_pixels`/`max_surface_bytes`/`max_wall_ms`/`derived_bytes` with real defaults verified against `budgets.py`). | — (doc) |
| CR-3 | P3 (disc.) | CI installed `pypdfium2` but nothing used it | Added a CI step: render an A4 PDF from the installed wheel and open it with `pypdfium2`, asserting 1 page at 595.28×841.89 pt. | (CI) |
| CR-5 | P3 (disc.) | Backend docstring implied cache==no-cache is pixel-exact | Rewrote the docstring: cold==warm is the bit-exact gate; enabling-vs-disabling the cache is ~1:1 (two resamples vs one) for cover/contain, far under the golden budget. | — (doc) |
| — | (found) | `doctor` human table silently stripped the bracketed precedence source (`[default (~/.arcavex)]`) as Rich markup | Escape `check.detail` with `rich.markup.escape` before adding the table row. Pre-existing; surfaced while regenerating the transcript; sits on the DX-1 trust surface. | covered by live transcript (source now visible) |

## Exit-code rationale (DX-2)

`ARC-EXP-001` maps to **exit 1** (validation/authoring error, §6.1.3): an unwritable/invalid output
path is a user-side problem, not an internal engine bug (5), a resource budget (4), or a missing
*input* (3 — inputs, not the output). It falls through `_exit_code_for` to `EXIT_VALIDATION` with no
special-casing, so the exit table stays consistent.

## Verification transcript (this machine, Windows 11 / Python 3.12.13 / skia-python 144)

```
pytest tests -q                         569 collected → 568 passed, 1 skipped (exit 0)
  skip: test_file_safety.py symlink (Windows account lacks symlink privilege; env-gated)
ruff check src tests                    All checks passed!
mypy src/arcavex/kernel --strict        Success: no issues found in 12 source files
lint-imports                            Contracts: 5 kept, 0 broken
```

### Determinism re-verified (cross-process, each format rendered twice in separate processes)

```
jpg  (hello-poster square, default q90)   IDENTICAL  b0cc67e9612b
webp (hello-poster square, default q90)   IDENTICAL  bf1f77817a09
pdf  (ipen-bilingual a4, fa)              IDENTICAL  42579356f4ec   (matches code-review hash)
png  (hello-poster square)               IDENTICAL  91f91c93792d   (matches code-review hash)
```

WebP's hash differs from the code review's `e5d8f245` because the default quality changed 100→90;
it remains byte-identical across processes (the property that matters). PDF and PNG hashes are
unchanged.

### DX-2 fixed behavior (live CLI)

```
$ arcavex render examples/hello-poster/... -o <path>/isafile/out.png   # 'isafile' is a file
ERROR ARC-EXP-001 Could not write the output file '...\isafile\out.png': Cannot create a file
  when that file already exists (...\isafile\out.png)
  hint: Check the output path is writable and its parent directory exists.
EXIT: 1
```

## Real packaged-install output (clean venv, outside the dev tree)

```
$ uv build --wheel
Successfully built dist\arcavex-0.1.0-py3-none-any.whl
$ uv venv cleanvenv ; uv pip install --python cleanvenv/... dist/arcavex-0.1.0-py3-none-any.whl
 + arcavex==0.1.0  + skia-python==144.0.post2  + typer==0.27.0  ... (22 deps)

$ arcavex doctor            # run from a neutral directory, no dev tree
Arcavex engine 0.1.0
  python    ok  Python 3.12.13
  skia      ok  skia-python 144.0.post2
  icu       ok  ICU available (skia.Unicode built)
  fonts     ok  4 bundled families: Estedad, Inter, Lalezar, Vazirmatn
  exporters ok  png, jpeg, webp, pdf all available
  cache     ok  derived cache=C:\Users\...\.arcavex\cache\derived; budget=256000000 bytes
  temp_dir  ok  Writable temp dir: C:\Users\...\AppData\Local\Temp
  paths     ok  home=C:\Users\...\.arcavex [default (~/.arcavex)]; preview cache=...\cache\preview
  config    ok  config.toml absent (...); default dpi=per-format [default]
        (paths and cache now agree on the home root — DX-1; the bracketed source renders — markup fix)

$ arcavex doctor --json     # emits REAL JSON, not a table (CR-1)
{"response_version": 1, "ok": true, "engine_version": "0.1.0", "checks": [ ...9 rows... ]}

$ arcavex render examples/hello-poster/template.yaml --data ... --format square -o hello.png
Rendered hello.png
$ arcavex render examples/ipen-bilingual/template.yaml --data ... --format a4 --locale fa -o ipen.pdf
inferred: data_overlay=data.fa.yaml
Rendered ipen.pdf
```

Installed `hello.png` SHA-256 `91f91c93792de0189aaaa1dabe99db691916cc3a4cf8c7016b457ff56dd11979`
== dev-tree render (byte-identical). Full transcript in `docs/packaged-install.md`.

## Files changed

- `src/arcavex/kernel/api.py` — DX-2 (`ARC-EXP-001` on OSError), DX-4 (`_DEFAULT_EXPORT_QUALITY`)
- `src/arcavex/kernel/contracts/types.py` — DX-4 (`ExportOptions.quality` default 90)
- `src/arcavex/clients/cli.py` — DX-4 (`--quality` help), doctor markup-escape fix
- `src/arcavex/services/doctor.py` — DX-1 (`_check_paths` via `home_dir()`)
- `src/arcavex/services/cache/derived.py` — CR-2 (disk LRU eviction, `disk_evictions` stat)
- `src/arcavex/builtin/backend_skia/backend.py` — CR-5 (docstring honesty)
- `docs/packaged-install.md` — CR-1 (regenerated transcript), `README.md` — DX-3/5/6
- `CHANGELOG.md`, `IMPLEMENTATION_LEDGER.md` — remediation notes
- `.github/workflows/ci.yml` — CR-3 (pypdfium2 PDF-open validation)
- Tests: `test_doctor.py`, `test_explain.py`, `test_derived_cache.py`, `test_export_cli.py`

## Where to scrutinize

1. **Exit-code choice for `ARC-EXP-001` (exit 1).** Defensible as an authoring/usage error via the
   default fallthrough; a reviewer who reads §6.1.3's "missing… asset" as covering the output could
   argue exit 3. I chose 1 — the output is not a *missing input*.
2. **Default quality change touches WebP too.** Lowering the shared `ExportOptions.quality` default
   to 90 changes lossy-WebP default output (still deterministic); only JPEG was flagged. Rationale:
   one default value, 90 benefits WebP identically, no per-format divergence.
3. **Disk-eviction budget unit.** The disk tier is bounded by the same configured byte budget as
   memory, but measured in real PNG bytes (memory uses decoded `w*h*4`). One budget number, two
   natural measures — confirm that matches the §4.7 intent.
4. **Reachability exemption list** (`_REACHABILITY_EXEMPT` in `test_explain.py`) — 7 legacy/reserved
   codes with documented reasons. Confirm none should instead be raised.

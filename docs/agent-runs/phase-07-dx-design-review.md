# Phase 07 — DX & design review (export and release hardening)

Reviewer: Sonnet (DX/design), parallel to a correctness/determinism code review. Commit under
review: `f5270ca`. Scope: spec §6.3 DX rigor, §12 README executability, export/release DX, visual
output quality. All testing done from `C:\Users\payam\Projects\Arcavex` against
`.venv\Scripts\arcavex.exe`; scratch artifacts under `outputs-tmp/dx7/`. Production code and tests
were read, not modified.

## Verdict: **remediate**

The export surface itself is excellent — CLI ergonomics, JSON reports, determinism, and the
packaged install all held up under real use. But two findings are release blockers for a v0.1 DX
gate: `doctor` reports two contradictory home directories in the same JSON payload (undermines the
one tool a confused user reaches for), and a real write-failure (unwritable output path) is
promised a friendly `ARC-EXP-001` diagnostic that the code never actually raises — it falls through
to "internal engine error" instead. Neither is hard to fix; both should block sign-off because they
sit exactly on the trust surface a release-gate review exists to protect.

## Findings

### DX-1 (P1) — `doctor` reports two different "home" directories in one run

**Did:** Ran `arcavex doctor --json` with `ARCAVEX_HOME` unset.
**Happened:** The `cache` check reports `derived cache=C:\Users\payam\.arcavex\cache\derived`
(correctly following `fsutil.home_dir()`, which defaults to `~/.arcavex`). The `paths` check in
the same JSON payload reports `home=C:\Users\payam\AppData\Local\Temp\arcavex [default (OS temp)]`
— a different directory, with a different default rule. `_check_paths()` in
`src/arcavex/services/doctor.py:211-230` hand-rolls its own home-resolution instead of calling
`fsutil.home_dir()` (used by `cache_root()`, the library, and everywhere else). One of these two
answers is simply wrong about where Arcavex's global state lives by default, and they disagree
inside a single command's output — the exact scenario a user runs `doctor` to resolve.
**Must change:** `_check_paths()` should call `fsutil.home_dir()` for its default, not
`tempfile.gettempdir()/arcavex`. Add a test asserting `doctor`'s `paths` and `cache` checks report
the same home root when `ARCAVEX_HOME` is unset.

### DX-2 (P1) — Unwritable output path surfaces as "internal engine error," not the documented `ARC-EXP-001`

**Did:** `render ... -o outputs-tmp/dx7/isafile/out.png` where `isafile` is an existing regular
file (not a directory) — a realistic typo/permissions scenario.
**Happened:**
```
ERROR ARC-INT-999 Render failed unexpectedly
  hint: This is an internal engine error. Detail: FileExistsError: [WinError 183] Cannot create a
  file when that file already exists: 'outputs-tmp\\dx7\\isafile'
EXIT: 5
```
`ARC-EXP-001` ("Export failed" — "Check the output path is writable and the disk has space") is
registered in `diagnostics_catalog.py:804-808` and documented at
`docs/diagnostics/ARC-EXP-001.md`, and describes this exact failure. But it is **never raised
anywhere in `src/arcavex`** — grepping the source finds it only in the catalog registration. The
top-level `except Exception` in `render_file` (`src/arcavex/kernel/api.py:1401-1408`) catches the
raw `OSError` and reports it as an internal failure with exit 5, which per the exit-code table
means "internal engine error" — telling a user their unwritable path is an engine bug, not a
located, actionable problem. `tests/unit/test_explain.py` only checks that every catalog code has
a docs file; nothing asserts the code is actually reachable, so this gap has no test coverage to
catch it.
**Must change:** Wrap the actual output write (wherever the exporter/atomic-write call sits — check
`_render_file_inner` and the exporter registry dispatch) in a targeted `except OSError` that raises
`ARC-EXP-001` with the OS error text and the output path located. Add a test that renders to a
path whose parent is a file (or an unwritable directory) and asserts exit 4 or a located
`ARC-EXP-001`, not `ARC-INT-999`/exit 5.

### DX-3 (P2) — PDF bleed is a real, working feature that is entirely undocumented and unused

**Did:** Read `src/arcavex/builtin/export_pdf/boxes.py`, `services/template/compiler.py:1056-1060`,
and grepped the whole repo for `bleed:`.
**Happened:** A format's `canvas:` block accepts a `bleed: <dim>` key that grows the PDF's
`MediaBox`/`BleedBox` beyond the `TrimBox` (the mechanism spec §4.6 and the phase-7 brief call out
as "must be first-class"). It is correctly wired end to end — but **zero** templates in the repo
(including the shipped `examples/`) use it, README's "Template anatomy → formats:" section
(README.md:170-171) shows only `{width, height, dpi}` with no mention of `bleed`, and the rendered
`ipen-bilingual` A4 PDF I produced has `MediaBox == TrimBox == BleedBox` (no bleed) since the
example never sets one. A user following the README to get "A4 + bleed" print-ready output has no
way to discover the feature exists short of reading source.
**Must change:** Document `bleed:` under README's `formats:` canvas section (one line + example),
and either add a `bleed:` example to `ipen-bilingual`'s `a4` format or ship a dedicated print
example. Bonus: `doctor` or `template inspect` could surface a format's resolved bleed value so a
user can confirm it took effect without opening a PDF inspector.

### DX-4 (P2) — Default JPEG quality (100) defeats the point of choosing JPEG

**Did:** Rendered `hello-poster` and `ipen-bilingual` to JPEG at the CLI default (no `--quality`)
and at explicit 85/95/40, and compared file sizes against the PNG of the same scene.
**Happened:** `ExportOptions.quality: int = 100` (`kernel/contracts/types.py:134`) is the default
when `--quality` is omitted. For `hello-poster` (flat colors, text) the default JPEG is **71,707
bytes**, bigger than the **30,998-byte PNG** of the identical frame — encoding to JPEG made the
file *larger* than a lossless format, with no warning. For `ipen-bilingual` (a busier scene with a
crosshatch texture), default-quality JPEG is 342,076 bytes vs. **128,443 bytes at `--quality 85`**
— a 2.7× size difference — and I could not see any visible artifact difference between the two at
normal viewing size (both screenshots attached below). `--help` documents the flag's range
(`1<=x<=100`) but never states the default value, so a user has no signal that omitting `--quality`
silently asks for a near-lossless (and often counterproductively large) encode.
**Must change:** Either lower the default to a conventional value (85 is the industry-standard
"visually lossless, small" default and tested clean here), or — if 100 is intentional for
determinism/parity reasons — state the default explicitly in `--help` and README, and note the
size trade-off so a user isn't surprised their "smaller" JPEG export is bigger than PNG.

### DX-5 (P3) — README's "Known limitations" section contradicts the CHANGELOG about the derived cache

**Did:** Cross-checked README.md against CHANGELOG.md.
**Happened:** README.md:450-451 (Known limitations → Asset store) still reads: "The derived-variant
LRU cache (downscaled thumbnails under a byte budget) is deferred to a later phase." CHANGELOG.md's
`[0.1.0]` entry (the phase this review covers) lists "**Derived-asset LRU cache**
(`$ARCAVEX_HOME/cache/derived/`)..." as shipped, and `arcavex doctor` reports a live
`cache: derived cache=...; budget=256000000 bytes`. The feature is real and I verified cold==warm
byte-identical output for it (see below) — README just wasn't updated when the "later phase"
arrived.
**Must change:** Delete or rewrite that bullet in README's Known limitations.

### DX-6 (P3) — `config.toml`'s `[budgets]` and `[cache]` tables are undocumented in README

**Did:** Read README's "Runtime configuration precedence (§6.3)" section and grepped for
`[budgets]`/`[cache]`/`derived_bytes`.
**Happened:** The precedence section documents only `[render] dpi` as a worked example. The
`ARC-RND-020` diagnostic I triggered correctly tells the user to "raise `[budgets].max_dimension`
in `config.toml`" — but README never states that a `[budgets]` table exists, what keys it has
(`max_dimension`, `max_pixels`, `max_surface_bytes`, `max_wall_ms`, per `services/budgets.py`), or
that `[cache].derived_bytes` controls the cache budget doctor reports. A user acting on the
diagnostic's own hint has to go read source to know the key is real and spelled correctly.
**Must change:** Add a short table (or two lines) listing the `[budgets]` and `[cache]` keys beside
the existing `[render] dpi` example.

## What impressed

- **Export CLI ergonomics are genuinely good.** Format-by-extension "just works," `--help` states
  ranges and which flags apply to which format, and the bad-extension diagnostic
  (`ARC-EXP-011`) lists every valid extension in the hint — no guessing.
- **Determinism holds up everywhere I poked it.** Repeated PNG/JPEG/WebP/PDF renders are
  byte-identical; the packaged-install wheel produced a `hello.png` with the *exact same*
  `content_sha256` as the dev-tree render, and the PDF's embedded `/Subject` render-signature
  matches the SHA-256 of the equivalent flat PNG bit-for-bit — a nice, verifiable provenance touch.
- **`ARC-RND-020` (budget) is a model diagnostic.** Triggered it with a 40000×40000 canvas; the
  message names the exact number, the exact budget, exit code 4, and the exact `config.toml` key
  to raise it (`[budgets].max_dimension`) — no guesswork.
- **Packaged install worked cleanly first try**: `uv build --wheel`, fresh `uv venv`, install,
  `doctor --json` (all green, ICU/fonts resolved with no dev tree), then rendered both quick-start
  examples from a neutral directory with absolute paths — byte-identical to the dev-tree output.
  `docs/packaged-install.md`'s transcript is accurate and reproducible.
- **`docs/performance.md` is honestly written.** It reports two missed p95 targets (raster-effect
  render time, cold start) with real numbers and a clear cost breakdown per effect, rather than
  hiding or rounding them away — exactly the kind of "record actuals, don't fake" the brief asked
  for.

## Visual-quality table

Judged by eye at normal viewing size (screenshots read via the Read tool); "artifacts" means
visible blocking/ringing, not file-size.

| Format | hello-poster (flat color + text) | ipen-bilingual fa (crosshatch texture + RTL text) |
|---|---|---|
| PNG (reference) | Clean. | Clean. |
| JPEG, default quality (100) | Indistinguishable from PNG. **71.7 KB vs. PNG's 31.0 KB — larger than PNG for no visual gain.** | Indistinguishable from PNG. 342 KB. |
| JPEG, `--quality 85` | Not separately tested (scene too simple to show a gap). | Indistinguishable from PNG/q100 by eye; **128 KB — 2.7× smaller than default**. Good default candidate. |
| JPEG, `--quality 40` | Still visually clean on this flat scene (19.7 KB) — not a fair worst-case test since there's no gradient/photo content to stress. | Not tested. |
| WebP, default | Indistinguishable from PNG. 25.6 KB (smallest of the three at default settings). | Indistinguishable from PNG. 138.7 KB. |
| PDF (A4, fa, raster-embedded) | N/A (square-only example) | Valid PDF (parsed `MediaBox`/`TrimBox`/`BleedBox`, all `595.28×841.89 pt` = exact A4). Raster embedded at full render resolution (2480×3508 px @ 300 dpi) inside a `/DeviceRGB` `/XObject` with an `/SMask` alpha channel — same pixels as the PNG render of the same scene (confirmed via the embedded `/Subject` render-signature matching the PNG's SHA-256). 1.12 MB, larger than the PNG (884 KB) as expected for a PDF wrapper around an uncompressed-ish raster. |

No format produced visibly worse output than PNG at any tested quality on these two example
scenes. The one real issue is the **default JPEG quality being wasteful, not lossy** (DX-4).

## PDF DX

- **Physical sizing: correct.** Verified by raw-parsing the PDF's page dictionary:
  `MediaBox = TrimBox = BleedBox = [0 0 595.275591 841.889764]` pt, which is exactly 210mm×297mm.
- **Bleed: works but undiscoverable** — see DX-3. No CLI flag; it's a template-authored `bleed:`
  canvas field, which is a reasonable design (bleed is part of the physical spec, not a per-render
  choice) but it needs to be *documented as such*, and right now it isn't anywhere a user would
  find it.
- **"Raster RGB, not vector/CMYK" is stated honestly** — README says so plainly ("PDF is
  raster-embedded RGB at the target DPI... Vector-preserving PDF and CMYK/PDF-X remain future
  work" per CHANGELOG, and the brief's non-goals confirm this is intentional scope, not a hidden
  gap). A print shop expecting vector text or CMYK separations would be surprised, but the docs do
  not oversell the capability — this is the one place I'd call the honesty bar met cleanly.
- **A4 print-ready in one command**: yes — `--format a4` (when the template declares one) plus
  `-o out.pdf` is all it takes; no extra flags needed for correct physical size.

## Packaged-install DX

Followed `docs/packaged-install.md` verbatim (with `uv build --wheel` + `uv venv` + `uv pip
install` against the built wheel, since `uv build --wheel -o` was used for a scratch output
directory instead of the default `dist/`): wheel built cleanly, contains 16 bundled font files
under `arcavex/_bundled/fonts/`, installed 22 resolved dependencies with no manual intervention,
`doctor --json` passed every check from a neutral directory outside the dev tree, and both
quick-start renders (`hello-poster` PNG, `ipen-bilingual` fa A4 PDF) produced **byte-identical**
`content_sha256` values to the dev-tree renders from earlier in this session. This is a strong,
verified result — the doc's claims hold.

## Cache / budget DX

- **Budget diagnostics are actionable** — see DX-6 above and the ARC-RND-020 example under "What
  impressed." Exit code 4, located, names the config key.
- **Cache cold==warm identity confirmed**: rendered `pop-art-grid` into a fresh, empty
  `ARCAVEX_HOME` (cold cache) and again immediately after (warm cache); both produced the identical
  `content_sha256`. The cache is invisible in the sense that matters (never changes output).
- **Cache is configurable** via `[cache].derived_bytes` in `config.toml` (confirmed in
  `services/config.py`) and `doctor` reports the resolved budget — but, per DX-6, this key isn't
  documented in README's config-precedence section, only discoverable by reading `doctor`'s output
  or source.

## README executability audit (§12)

README.md has exactly **one** fenced `bash` command block (lines 8–11, the quick-start `arcavex
render ... -o out.png`). Ran it verbatim from the repo root: succeeded, produced a 30,998-byte
`out.png`, exit 0. Every other code fence in the file is an illustrative YAML/text snippet (template
anatomy, patch syntax), not a runnable shell command, so there is nothing else to literally execute
from a fence. I additionally spot-checked commands named in the Commands table that aren't in
fences: `effects list`, `style list`, `explain ARC-TPL-100`, `doctor --json` — all matched their
documented behavior and output shape.

The one substantive README accuracy problem found is **not** in the runnable command but in prose:
the stale "derived cache... deferred to a later phase" line (DX-5) and the missing `bleed:`/
`[budgets]`/`[cache]` documentation (DX-3, DX-6) above. The Commands table, exit-code table, and
template-anatomy prose I checked against actual CLI output were otherwise accurate.

## Release readiness

- `arcavex --version` → `arcavex 0.1.0`, matching `CHANGELOG.md`'s `[0.1.0]` entry and
  `pyproject.toml`. Consistent.
- CHANGELOG.md is well-organized (Phase 7 additions vs. earlier phases vs. determinism guarantees)
  and readable; no complaints.
- `doctor` is useful for diagnosing a broken install *except* for the home-directory contradiction
  in DX-1, which is exactly the kind of thing that erodes trust in the one tool meant to build it.
- `.github/workflows/ci.yml` and `docs/testing.md` are consistent with each other and with the
  brief's intended matrix (linux-x86_64 + macos-arm64 + linux-aarch64, per-platform goldens,
  separate `packaged-install` job); I did not run CI (out of local scope per the brief) but the
  workflow reads correctly and matches the documented strategy.

## Files touched

None — this review is read/render-only. Scratch renders, the built wheel, and the clean-venv
install live under `outputs-tmp/dx7/` (gitignored) and can be deleted freely.

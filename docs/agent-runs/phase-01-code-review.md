# Phase 01 code review — authoring loop (commit 1004936)

Reviewer: Fable 5 (adversarial, read-only). Verification was by execution: every scope item
was exercised with real seeded scenarios under `outputs-tmp/review1/`, plus a scripted live
watch session. The implementing agent terminated before reporting, so nothing was taken on
trust from the commit message.

## Verdict: REMEDIATE

Two P1s: the RR-5 carry-over (default output name announced before rendering) is still not
satisfied on the path where it matters (render-stage failure), and the `--locale` request
path required by scope item 1 does not exist on the CLI at all. Everything else in the phase
is in genuinely good shape — the structural constructs, split loader, function registry,
variable enforcement, doctor/explain, and the watch loop all verified correct under
execution, with located diagnostics and correct exit codes throughout.

## Gates (all pass)

```
.venv\Scripts\python.exe -m pytest tests -q          # 166 passed, exit 0
.venv\Scripts\python.exe -m ruff check src tests      # clean
.venv\Scripts\python.exe -m mypy --strict src/arcavex/kernel   # clean (12 files)
.venv\Scripts\lint-imports.exe                        # 3 contracts kept, incl. NEW
                                                      # "services do not import builtin"
```

## What was verified by execution (summary)

- **Acceptance commands**: all eight from the brief ran with expected exit codes.
  `template new` → renders out of the box (exit 0); inspect --json complete
  (variables/formats incl. resolved pt + dpi/nodes with types/functions/preview_data/
  version/is_split); split → re-render **byte-identical sha256** pre/post split; re-split
  refused (ARC-TPL-071, exit 1); doctor --json valid and ok; explain known/unknown/lowercase
  codes (exit 0/1/0).
- **Split semantics**: inline+sidecar duplicate → located ARC-TPL-097 (file, line 41,
  keypath) exit 1; comments preserved through split; diagnostics in split templates point at
  the sidecar file (test verified); dir-vs-file compile equivalence covered by canonical-hash
  test.
- **Structural constructs**: reorder of a keyed collection produced the identical expanded ID
  set (`row[ann]`, `tag[ann][vip]`, nested suffix composition correct); `key: "{{ loop.index }}"`
  → ARC-TPL-057 warning; duplicate key → ARC-TPL-058 error; missing key → ARC-TPL-055;
  1001 items → ARC-TPL-063 (mapped to exit 4); `if: "{{ note is not none }}"` includes/excludes
  correctly, including against an optional-without-default variable; `loop.index/first/last`
  usable in text.
- **Functions**: unknown function → ARC-TPL-060 listing all nine registered names (verified
  through the production registry table, not the test fallback); `locale_digits` fa digits
  bijective (۰۱۲۳۴۵۶۷۸۹), decimal/percent/negative pass-through, unknown locale is a located
  error; `contrast_color` verified against the WCAG 0.179 crossover including both sides of
  the pivot (#747474→white, #767676→black; black-on-red is the correct WCAG answer);
  format/min/max/round/len behave.
- **Variables**: full type matrix probed. RR-1: `type: strnig` → located ARC-TPL-016 listing
  valid types. RR-2: int and float for declared string coerce with ARC-TPL-018 warning; all
  other mismatches (incl. bool↔number both directions) stay hard ARC-TPL-015 errors; defaults
  type-checked with template-line locations; enum enforced; multiple variable errors
  aggregate in one run. Undeclared+unsupplied reference → ARC-TPL-014 citing the referencing
  node's file/line/keypath.
- **doctor**: --json shape valid; every probe isolated per-check in code; facade wraps any
  probe explosion into a fail row (could not make it crash).
- **explain**: coverage test enumerates emitted codes ⊆ documented; docs/diagnostics/*.md are
  generated from the catalog with a byte-exact mirror test + orphan test, so drift is
  impossible. Spot-checked 8 entries for substance — concise cause + typical fix, all good.
  (Deviation: brief said entries "loaded from package data"; the canonical form is a
  mypy-checked Python catalog with generated md. Rationale documented in the module docstring;
  the sync tests make this sound. Accepted.)
- **preview**: same invocation → identical stable path and identical content sha across runs
  (also proves no wall-clock in rendered bytes); compile ~10-15 ms, render ~80-240 ms for the
  scaffold and hello-poster — loop latency well under the 2 s target.
- **watch (real background session, split template)**: initial line; edited data.yaml →
  `changed=<file> compile=14.0ms render=85.2ms -> <path>` with preview mtime+sha changed;
  seeded `type: grup` mid-watch → `render failed (kept last good preview)` + first located
  diagnostic (ARC-TPL-031, file+line+keypath), **preview bytes and mtime byte-intact**, loop
  survived; reverting the file → recovery re-render. Atomic write is mkstemp + os.replace in
  the destination directory (api.py) — no torn PNG window.
- **RR-3**: render-time ARC-AST-002 (undecodable image) now carries file/line/keypath (exit 3);
  solver ARC-LAY-030/031/020/014 all located via the SourceRef threaded through
  CompiledNode→LayoutNode (excluded from serialization so canonical hashes stay path-free).
- **RR-4**: a template with `styles:` + format `patch:` + malformed locale shape reported all
  three located errors in ONE validate run.
- **UTF-8 fix**: Persian enum values in diagnostics survived PowerShell 5.1 redirection in
  both human and JSON output, exit 1 correct.
- **Registry purity**: evaluator has no hardcoded function table; `builtin/template_fns`
  wraps the single canonical `services/template/functions.py` dict; bootstrap injects a
  registry-backed table; a new import-linter contract enforces services↛builtin. The
  `default_function_table()` fallback resolves the same canonical dict and is reachable only
  when a Compiler is constructed without wiring (tests) — acceptable, not a parallel table.

## Findings

### CR-1 (P1) — RR-5 still unmet: default output name not announced before rendering, and never on render failure
`src/arcavex/kernel/api.py:372-382`, `src/arcavex/clients/cli.py:183-188`.
Evidence: `arcavex render rr/img.yaml` (undecodable asset, no `-o`) → exit 3 with the
ARC-AST-002 diagnostic but **no `inferred: output=…` line at all** — the `except
DiagnosticError` / `except Exception` paths in `render_file` construct `RenderResult` without
`inferred`, dropping the already-computed output name. On success the name is printed only
after the facade call returns, i.e. after rendering (the code comment reinterprets RR-5 as
"before the render confirmation line"). Phase-0 re-review RR-5 flagged exactly this failure
case; the brief promoted it to required Phase 1 work, and §6.3 says "deterministic and shown
before rendering". Required fix: resolve the default output name up front (it depends only on
template stem + resolved format) and carry `inferred` on every RenderResult path; have the
CLI print inferences before invoking the render, or restructure so the facade reports the
resolved output before pipeline execution.

### CR-2 (P1) — `--locale` request path does not exist on the CLI
`src/arcavex/clients/cli.py` (no command declares a locale option; grep confirms zero
matches). Evidence: `arcavex render my-card --format square --locale fa` → Typer usage error,
exit 2. Scope item 1 requires: "if a locale is REQUESTED (--locale) in Phase 1, emit the
existing not-supported-yet diagnostic". The compiler path exists and works
(`compiler.compile(..., locale='fa')` → ARC-TPL-091) but is unreachable from the CLI, so a
user requesting a locale gets a usage error instead of the located not-supported diagnostic
(and the spec §6.1.1 example `arcavex preview --format story --locale fa --watch` is
unparseable). Required fix: add `--locale` to render/validate/preview (and template check)
passing through to the facade.

### CR-3 (P2) — `repeat:` + `if:` on the same child silently ignores the `if`
`src/arcavex/services/template/compiler.py:739-746` — `_expand_child` checks `"repeat" in
child` first and never looks at `if`. Evidence: a child with `repeat: "{{ items }}"` and
`if: "{{ false }}"` compiled and expanded both items, no diagnostic. This is a silent drop of
an authored directive — the exact class of behavior this codebase rejects elsewhere
(ARC-TPL-093/095/096). Required fix: located error for the combination (or defined per-item
semantics, but an error is the Phase 1-consistent choice).

### CR-4 (P2) — preview path breaks §4.1.1 path equivalence
`src/arcavex/kernel/api.py:552` hashes the raw supplied path. Evidence:
`preview examples/hello-poster/template.yaml …` → `…\1bfd61c126df2553.square.png`;
`preview examples/hello-poster …` → `…\3dc5b7f807097c3c.square.png`. Same template, two
"stable" preview files, so a viewer pointed at one goes stale when the author switches
spellings. Same class: `render` default output stem differs (`template.square.png` vs
`my-card.square.png`). Required fix: normalize through `resolve_template_path` (hash the
resolved `template.yaml`; consider the directory name for the default render stem).

### CR-5 (P2) — explicit `null` for an optional variable is a hard error while omission is fine
`src/arcavex/services/template/compiler.py:296-299` (omitted optional → `None`, no check) vs
`:347-392` (`_check_type` has no None branch). Evidence: data `s: null` for optional
`type: string` → ARC-TPL-015 "should be string but got NoneType" (exit 1); deleting the line
→ compiles, `s is not none` guard works. In YAML, `s:` with an empty value IS null, so the
most natural way to author "no value" errors while the less obvious way succeeds. This is an
interaction gap of the orchestrator's optional-as-none fix. Required fix: treat a supplied
None for a non-required variable as equivalent to omission (skip type/enum check, bind None);
keep it an error for required variables.

### CR-6 (P2) — `template inspect` on a broken template: exit 0, diagnostics invisible in human mode
`src/arcavex/services/authoring.py:192` hardcodes `ok=True`; `src/arcavex/clients/cli.py:419`
branches on it. Evidence: inspect of a template whose compile fails printed `nodes:` (empty)
with no diagnostics and exited 0; the collected compile diagnostics exist only in the JSON
payload while `"ok": true` says nothing is wrong. Required fix: reflect compile failure in
the report (e.g. `ok=False` or a distinct `compiled: false` field), print the diagnostics in
human mode, and map the exit code per §6.1.3.

### CR-7 (P2) — watch startup race loses saves; the shipped test masks it instead of fixing it
`src/arcavex/clients/watch.py:64-76` — the initial render runs before `watchfiles.watch()` is
first iterated, so a save landing in that window is lost and no re-render ever happens.
Evidence: my first scripted session wrote data.yaml immediately after the initial-render line
and observed no re-render within 15 s; with a warm-up delay the same edit re-rendered in
~100 ms. `tests/e2e/test_preview.py:97-103` acknowledges the race ("watcher startup race")
and re-touches the file in a loop until the render lands — the workaround lives in the test,
so CI can never catch a regression that widens the window. Required fix: construct the
watcher before the initial render (or do an initial rescan after the watcher is live), then
drop the retry loop from the test.

### CR-8 (P3) — data-file diagnostics discard available line numbers
`src/arcavex/services/template/compiler.py:230` converts the data mapping with `_to_plain`
before validation, so all data-cited diagnostics carry `line=None` (visible in every matrix
probe: `[data.yaml:None s]`). The code comment "the data file has no per-variable line to
cite" is inaccurate — ruamel had the line info until `_to_plain` dropped it. Fix: capture
per-key lines from the CommentedMap before flattening.

### CR-9 (P3) — assets outside the template directory are not watched
`src/arcavex/clients/watch.py:23-32` watches only the template root dir + data file. §6.3
("saving any dependent … asset file triggers one rebuild") and the brief ("referenced local
assets") include assets referenced via `../`. In-dir assets are covered. Fix: collect
referenced asset paths from the compile result and add out-of-tree parents to the watch set.

### CR-10 (P3) — CR-13 ticket note missing
The brief asked for a code TODO referencing the CR-13 canonical-float ticket next to
`canonical_hash`; `grep -rn "CR-13" src/` is empty.

### CR-11 (P3) — inspect JSON cannot distinguish "no default" from `default: null`
`src/arcavex/kernel/api.py:157` (`default: Any = None`) + `authoring.py:260`. Both render as
`"default": null`, so a machine consumer (the AI workflow §6.3 targets) cannot recover the
declared contract exactly. Fix: only include the field when declared, or add `has_default`.

### CR-12 (P3) — stale evaluator docstring undermines the registry story
`src/arcavex/services/template/expressions.py:7` still says "the functions
len/upper/lower/format" — the set is registry-resolved and nine built-ins strong. Cosmetic,
but it is the exact spot a future reader will check for hardcoded-table remnants.

### CR-13 (P3) — programmatic stop of the watch loop is event-gated
`watch.py:74` passes `rust_timeout=0`, so a set `stop_event` is only observed after the next
filesystem event; the e2e test leaks its daemon thread via `join(timeout=10)` when no event
arrives. Ctrl+C is unaffected (watchfiles raises KeyboardInterrupt). Fix: a finite
rust_timeout (e.g. 500 ms) with `yield_on_timeout` handling, mostly for test hygiene.

### Notes (no action required)
- Index-key detection is substring-based (`"loop.index" in key_raw`); adequate for the
  declared idiom, could false-positive on a field literally named `loop.index`.
- `round()` uses Python banker's rounding (`round(2.5) == 2`) — deterministic, but worth a
  doc line eventually.
- Orchestrator fix 1 (optional-as-none) is otherwise sound: verified with `is not none`,
  `| default(...)` (the scaffold's subtitle exercises exactly this), and interpolation
  (None → empty string). Fix 2 (UTF-8 at entry) verified under PowerShell; per-command
  `--json` re-forcing is redundant but harmless.

## Commands run (abridged)

```
pytest -q; ruff check src tests; mypy --strict src/arcavex/kernel; lint-imports
arcavex template new / render (dir + file, with/without -o, --json) / template inspect --json
arcavex template split (+ re-split refusal) → render sha256 equality pre/post
arcavex validate: duplicate section, RR-4 aggregate (styles+patch+bad locale), locales.yaml
  sidecar (valid + malformed), undeclared variable, over-constrained node, Persian enum via
  PowerShell (human + JSON)
arcavex render: undecodable PNG with/without -o (RR-3 location, RR-5 failure path, exit 3)
arcavex preview ×4 (dir vs file spelling, repeat-invocation stability, --json sha compare)
arcavex doctor --json (+ hostile TMP), arcavex explain (known/unknown/lowercase/--json)
Compiler probes: 10-case variable type matrix, repeat idx/dup/nokey/cap-1001/unknown-fn/
  repeat+if combo, reorder ID-stability incl. nested repeats, function unit probes
Scripted watch sessions ×3: save→re-render line+mtime+sha, seeded error→last-good bytes
  intact→recovery, startup-race reproduction
```

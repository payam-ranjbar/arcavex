# Phase 01 re-review — authoring loop (commit 1004936 + remediation working tree)

Reviewer: Fable 5 (fresh, adversarial, read-only on production code/tests). All scenarios
re-verified by execution under `outputs-tmp/rr1/` with fixtures of my own design, including a
live watch session and adversarial probes not present in any prior review.

## Verdict: ACCEPTED

Every gate passes; every original P1/P2 finding is verifiably fixed at root cause (not by
masking); both remediation-flagged risk areas hold up under attack; the three new diagnostic
codes are fully covered; the single deferral is confirmed cosmetic-only. My adversarial probes
found one new guidance-text defect and two small residuals — by this project's own severity
calibration (cf. DX-10's wrong-hint items) these are P3s, carried below with the first marked
top-of-backlog for an immediate fix.

## Gates (all pass)

```
.venv\Scripts\python.exe -m pytest tests -q          # 190 passed
.venv\Scripts\python.exe -m ruff check src tests      # clean
.venv\Scripts\python.exe -m mypy --strict src/arcavex/kernel   # clean (12 files)
.venv\Scripts\lint-imports.exe                        # 3 contracts kept, 0 broken
```

## Original findings — each reproduced-and-confirmed-fixed by execution

- **CR-1 (P1)**: `render` without `-o` on a render-stage failure (undecodable PNG) →
  `inferred: output=cr1.square.png` printed, then ARC-AST-002, exit 3. Same on a compile-error
  failure (exit 1) and on `--locale` refusal. The name now appears on every path, before the
  error/confirmation line. Residual letter-gap noted as RR1-3 (P3) below.
- **CR-2 (P1)**: `--locale fa` accepted on `render`, `validate`, `preview`, `template check`;
  all four emit located `ARC-TPL-091` (exit 1), no Typer usage error. The §6.1 preview+locale
  spelling parses.
- **DX-1a (P1)**: 3-item repeat with identical constraints → `ARC-LAY-040` warning naming the
  count and pointing at Phase 2 stacks; render still succeeds, exit 0.
- **DX-1b (P1)**: expression inside an anchor → `ARC-LAY-012` whose hint now says
  "'{{ }}' expressions are not evaluated inside anchors or offsets"; the explain entry names
  the expression-in-constraint cause explicitly.
- **DX-2 (P1)**: README verified current — repeat/if/`as:`/`key:` syntax with examples, all
  nine functions with signatures, split layout, the full command table (check/split/doctor/
  explain/watch), locale status, and an honest **Known limitations** section leading with
  repeat-overlap. The scaffold teaches a working `if:` and points at the README for `repeat`.
- **CR-3 (P2)**: repeat+if on one child → located `ARC-TPL-061`, exit 1. (But see RR1-1: the
  hint's suggested remedy doesn't compile.)
- **CR-4 (P2)**: preview path identical for dir vs file spelling
  (`d7c9ad94e204eb75.square.png` both ways); default stem identical
  (`card.square.png` both ways, verified via `--json` `inferred`).
- **CR-5 (P2)**: `note: null` for an optional variable renders exit 0 with the `is not none`
  guard excluding the node; `title: null` for a required variable → `ARC-TPL-014`, exit 1.
  Bonus probe: explicit null for a variable **with a default** correctly binds the default.
- **CR-6 (P2)**: inspect on a failing template prints the located diagnostics in human mode,
  exits 1; `--json` carries `ok:false`, `compiled:false`, and the diagnostics.
- **CR-7 (P2)**: live watch probe — a single save issued with **zero delay** after the
  initial-render line re-rendered in 169 ms wall; no retries anywhere. The retry-mask is gone
  from `tests/e2e/test_preview.py` (`test_watch_rerenders_on_single_save` asserts exactly one
  save → one re-render; `test_watch_stops_promptly_without_events` pins CR-13).
- **DX-3 (P2)**: `inspect --json` reports the authored tree: repeat nodes carry
  `origin:"repeat"` + `collection`/`loop_var`/`key`, if-nodes carry `origin:"if"` +
  `condition`; functions are objects with `signature` + `doc`; formats echo authored units
  (`"width": "600px"` beside `width_pt`); `has_default` distinguishes no-default
  (`false`, `default:null`) from a declared default (`true`, value present).
- **DX-4 (P2)**: three undeclared references reported in ONE `template check` run, each
  located at its referencing node.
- **DX-5 (P2)**: `direction: sideways`, `digits: klingon`, and an unknown key all reported in
  one run as located `ARC-TPL-099` with vocabulary hints.
- **DX-6 (P2)**: explain entries for LAY-012/TPL-070/TPL-071/TPL-097 each now carry cause
  taxonomy and boundary information the inline hint does not (LAY-012 names the
  expression-in-constraint cause; TPL-071 explains there is no reverse join; TPL-097 explains
  the no-precedence rationale).

## Remediation-flagged risk areas

**(a) Partial document for node-level reference errors.** Grepped every consumer of
`CompileResult.document`: `validate_template` (api.py:391), `render_file` (api.py:490), and
`render_preview` (api.py:702) all guard `document is None or has_errors(diagnostics)`;
`authoring.py:229` computes `compiled` from both. The only consumer that walks a partial
document is `collect_asset_paths` (api.py:764, checks `is None` only) — it feeds the watch
path set, is best-effort by design (wrapped in try/except), and never reaches layout/render;
walking the partial tree there is arguably desirable (watch the assets that did compile).
**No exploit found**: no path lets a partial document reach layout, render, or export. The
aggregation catch in the compiler is scoped to `all(d.code == "ARC-TPL-014")`, so mixed-error
children still fail fast (verified: a template with two 014s and one ARC-TPL-060 reported the
collected 014 plus the 060).

**(b) CR-7 residual window.** Better than claimed. The watcher (rust notify) registers when
the `watch()` generator is first advanced; the initial render runs inside the first yielded
tick — i.e. **after** registration — so a save landing before registration is simply
incorporated into the initial render's file read, and a save after registration arrives as a
change event. There is no window in which a save's *content* is lost. The remediation note's
"not captured until the next save" is conservative; the residual claim stands as inherent
and, in content terms, empty.

## New diagnostic codes (ARC-TPL-061, ARC-TPL-099, ARC-LAY-040)

All three: present in the catalog (explain resolves each with substantive cause+fix text),
docs/diagnostics/*.md files exist, and the mirror/coverage/orphan tests pass in the suite.
ARC-LAY-040 verified as severity=warning (exit 0 with render success).

## Diff sweep (compiler.py +254/-38, cli.py +66/-10) and adversarial probes

Read both diffs hunk-by-hunk. The suspicious-looking `data_lines` loop after the non-dict
data check is unreachable for non-dicts (that path raises). The CR-5 None-filter also makes
an explicit null for an *undeclared* variable count as unsupplied — consistent with the
null==omission rule, judged correct. `_print_preview_line` correctly drops `changed=` in
one-shot mode and only claims "kept last good preview" after a good render exists.

Probes run (beyond the reproductions): nested if-inside-repeat-node and
repeat-inside-if-node (both rejected — see RR1-1); wrapper-group nesting (works, with the
overlap warning composing through nested keypaths); did-you-mean (`{{ titel }}` →
"Did you mean 'title'?"); explicit-null-with-default; mixed 014+060 aggregation; data-file
line citation (`data.yaml, line 3` cited through leading comments); human inspect on
structural templates; doctor `paths` row (home + provenance + preview cache); split of a
comment-bearing template (render byte-identical pre/post, sha256 equal).

## New findings

### RR1-1 (P3, top of backlog) — ARC-TPL-061's suggested remedy does not compile
`src/arcavex/services/template/compiler.py` (hint), `docs/diagnostics/ARC-TPL-061.md`
(explain fix text), `README.md` ("nest them instead"). The hint says "make the 'if' construct
the repeat's 'node', or put the 'repeat' construct inside the if's 'node'" — both forms are
rejected with a confusing `ARC-TPL-030` ("requires a stable 'id'" at `…node.id`), because
`node:` accepts only plain nodes, never constructs. The working form is a wrapper group with
the inner construct in its `children:`. Escalating to `explain` repeats the same dead-end
advice. Fix: rewrite hint + explain + README line to the wrapper-group form and add a test
that the hint's recommended structure actually compiles. (Graded P3 per the project's DX-10
calibration for wrong-hint items; it is a ~4-line text fix, but it is the one place Phase 1
guidance actively misleads.)

### RR1-2 (P3) — human `inspect` origin tags swallowed by Rich markup
`src/arcavex/clients/cli.py` (`template_inspect` human branch): the `[if]`/`[repeat]` origin
tag is interpolated unescaped into `console.print`, so Rich parses it as a style tag and
renders nothing — `badge: text ` instead of `badge: text [if]`. JSON contract unaffected.
Escape the brackets (or use `console.print(..., markup=False)` / `rich.markup.escape`).

### RR1-3 (P3) — CR-1 letter-gap: inferences printed after the facade call returns
`src/arcavex/clients/cli.py:187-189`. Every exit path now carries and prints the default
output name before the confirmation/error line, which satisfies the substance of RR-5. But
the CLI prints only after `render_file` returns, so during a long render (or a mid-render
kill) nothing has been shown — §6.3's "shown before rendering" is met textually, not
temporally. The pieces exist to close it fully (compiler `resolve_paths` + the up-front
`_default_output_path`): resolve and print the inference before invoking the render.

### Notes (no action)
- Human `inspect` flattens the node tree (no nesting indication); acceptable for Phase 1, the
  JSON form is the contract surface.
- The watch banner's `…` is proper UTF-8 on the wire (a mojibake seen in one probe was the
  probe's own console decoding, not the product).
- `test_watch_rerenders_on_single_save` includes a 0.3 s settle before its single save; this
  orders the write after the initial render rather than masking the race — my live zero-delay
  probe is the proof the race is gone.

## Deferral judgment

**Orphan-comment-after-split: cosmetic-only, confirmed.** Split of the comment-bearing
scaffold: render byte-identical (sha256 equal) pre/post; the header comment stays sensibly
above `root:`; section-internal comments move with their section into the sidecar (with odd
but valid indentation). No semantic or parse impact. Deferring the ruamel comment surgery was
the right call.

## P3s to carry into the Phase 2 backlog

1. **RR1-1** — fix ARC-TPL-061 hint/explain/README to the wrapper-group nesting that actually
   compiles; guard with a test that compiles the hint's recommended structure. (First item.)
2. **RR1-2** — escape Rich markup in human `inspect` origin tags.
3. **RR1-3** — print render inferences before invoking the render (true "before rendering").
4. **CR-13 float-canonicalization ticket** — TODO is in place at
   `src/arcavex/kernel/ir/canonical.py:60`; resolve before canonical_hash gains a production
   caller (Phase 4), per the brief.

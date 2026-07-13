# Phase 02 re-review — layout, text, locales, masks, inspection (remediation `d8fadc3`)

Fresh strict re-review of the phase-02 remediation (diff `157b799..d8fadc3`), judged by
execution with independently authored fixtures. Probe artifacts under `outputs-tmp/rr2/`.
Working tree verified clean at `d8fadc3`.

## Verdict

**REMEDIATE** — narrowly. Nearly the entire remediation is verified genuinely fixed by my own
fixtures: every original P1/P2 I reproduced behaves correctly, the stack/anchor math is exact
against hand computation including nested-RTL and space_between cases, the six ipen renders are
design-passing, determinism holds byte-identically, and all four gates are green. But one
**P1** stands: the locale data layering order that ADR-0002 Decision 3 and the README both
adjudicate is **implemented inverted** — template `locales.<L>.data` overrides the user's
`--data` values, the exact "user data always outranks template data" guarantee the remediation
claims to deliver. It is untested in the suite (the DX-4 row was doc-only), so nothing caught
it. One P2 (acceptance-artifact content loss on a4/en) and a batch of P3s accompany it. The
fix is small (merge order in one function + a test) and everything else can stand as-is.

## Gates (all executed at `d8fadc3`)

| Gate | Result |
|---|---|
| `pytest tests -q` | 305 passed, exit 0 |
| `ruff check .` | All checks passed |
| `mypy --strict src/arcavex/kernel` | clean (12 files) |
| `lint-imports` | 3 contracts kept, 0 broken |

## Findings

### P1

**RR2-1 — locale data layering is implemented in the opposite order from ADR-0002 / README;
untested.** ADR-0002 Decision 3 and README §"Locales, data layering, and patches" both specify
defaults → template `locales.<L>.data` → user `--data` → user sidecar, with "user-supplied data
must always outrank template data". The implementation applies the inline locale overlay **on
top of** the user's base data: `_locale_data_overlays` returns `[inline, sidecar]` and
`_build_context` merges them over the already-loaded user data (`compiler.py:395-398`,
`764-777`). Probes (`outputs-tmp/rr2/ordertest/`, `deltest/`):

- user `--data` sets `m: "M-user"`, template `locales.fa.data` sets `m: "M-inline"` → final
  value is **M-inline** (spec'd answer: M-user);
- a `!delete` in the inline overlay deletes the **user's** value and, the key now being absent,
  the template default is resurrected (`a: A-user` + inline `a: !delete` → `A-default`) — the
  template can silently discard user data, which is precisely the DX-4 trap class.

Sidecar-over-everything and inline-over-defaults are correct; only the inline↔user-base pair is
inverted. No test asserts the precedence in either direction (`test_locales.py` covers merge
semantics and the sidecar inference only; the remediation's DX-4 row cites "(doc/adjudication)").
*Required fix:* apply the inline locale overlay **below** user data per the ADR (or formally
re-adjudicate and rewrite ADR-0002 + README), and add a test pinning the four-layer order with
a conflicting key in every layer.

### P2

**RR2-2 — ipen a4/en subtitle is silently clipped mid-sentence in the acceptance artifact.**
The A4 en render drops "and education": measured 99.0pt (3 lines) into the 66.0pt
(`max_lines: 2`) box, overflow state `clipped` per `layout inspect`; square and story show the
full sentence, and fa a4 happens to fit. The engine behaves exactly as configured — the flaw is
the shipped golden example loses words on one format×locale cell with no render-time signal,
and the phase's exit criterion is that this example renders correctly from one template across
all six. *Fix:* patch the subtitle on a4 (width/size, as was done for title/venue), or switch it
to `shrink_to_fit`. (Engine-side, a validate-time note when a golden's `clip` actually truncates
would have caught this — optional.)

### P3 (carry to Phase 3 backlog)

- **RR2-3** — ADR-0002/README claim "**both** overlay applications are reported as `inferred`
  breadcrumbs"; only the sidecar is (`compiler.py:766-777` — no breadcrumb for inline data).
  Align docs or add the breadcrumb (fold into the RR2-1 fix).
- **RR2-4** — default output naming: rendering `arcavex render template.yaml` from **inside** a
  directory template produces a hidden dotfile `.square.fa.png` (empty stem — relative path's
  parent name is ""). From the parent dir the name is correct (`prov.square.fa.png`). Resolve
  the template path before deriving the stem.
- **RR2-5** — the CR-13 warning mislabels its measurement: "one line is 96.0pt" for 20pt text —
  `solver.py:575` prints `result.height_pt` of the degenerate (full wrapped text) paragraph,
  not one line's height. The diagnostic's whole point is correct measured values.
- **RR2-6** — README intro (line 12) still documents the default output as
  `<template-stem>.<format>.png` — the locale segment (DX-3's fix, §6.3) is absent there and
  undocumented anywhere in the README.
- **RR2-7** — `_FIT_WIDTH_MARGIN = 0.5` (`solver.py:52`) is justified as guarding 1/1024pt
  quantization, but the max quantization error is ~0.0005pt — the constant is 500× the stated
  cause. It is benign and deterministic (verified), and plausibly papers over SkParagraph
  re-layout width sensitivity, but the comment misattributes and the magnitude is eye-tuned;
  correct the rationale and consider an epsilon sized to the real failure mode.
- **RR2-8** — a stack `fill` share clamped by `max` does not redistribute the freed space:
  two fills in a 300pt row, one `max: 50pt` → the other stays at its 150pt equal share and
  100pt goes dead at the row end. Doc-consistent ("equal split") but flexbox-unlike; document
  the non-redistribution explicitly or redistribute.
- **RR2-9** — the DX-8 overlap suppression ("one node fully contains the other") also hides a
  text node genuinely swallowed by an **unrelated** sibling shape (probe: `adv2.yaml` — the
  containment pair is unreported while the partial overlap is). Consider suppressing only
  fill-both-axes backdrops/ancestors, or reporting containment pairs tagged `contained` instead
  of omitting them.
- **RR2-10** — `template inspect --resolved` reports the **final** value for overridden ops:
  the format-layer row shows the locale's winning value, so what the format patch actually set
  is unrecoverable, and the human line ("= #ff0000 <- format:square (set) (overridden)") reads
  as if the format patch set the winner. Record the op's own value alongside the final one.
- **RR2-11** — `set` requiring an existing final field (CR-3 fix, documented in README) means a
  patch cannot add any schema-valid-but-absent optional field: `set: nodes.root.direction`
  fails when root declares no `direction`, `fit:`/`transform:` blocks can't be introduced.
  Locale patches flipping direction on undirected groups is a natural bilingual need; consider
  allowing `set` on schema-valid fields of the node type, or an explicit `add` op.
- **RR2-12** — ARC-TPL-051's hint lists `line_height` among "valid style fields" while setting
  it fails with ARC-TPL-053 "not supported in this build" — a mixed signal for one field.

## Original findings — reproduction results (own fixtures, all under `outputs-tmp/rr2/`)

- **CR-1** ✓ `template inspect --resolved -f square -l fa`: value set at template + format
  patch + locale patch reports final `#ff0000 <- locale:fa`, format row `effective: false`,
  header carries direction/digits; JSON `response_version: 1`. (Presentation nit → RR2-10.)
- **CR-2** ✓ `font_sze`, `kerning`, junk `fit.squeeze`, junk `paragraph.justfy` — each a
  located ARC-TPL-051 naming the node, keypath+line, **listing the valid fields**; exit 1.
- **CR-3** ✓ patch `set: nodes.t.style.font_sze` → located ARC-TPL-092 "unknown patch path
  field 'font_sze' (set modifies existing fields)".
- **CR-4** ✓ `h: {value: 100pt, max: 50pt}` + `w: {aspect: "2:1"}` → **100×50** (derives from
  the clamped axis; was 200×50).
- **CR-5** ✓ vstack child `w: {aspect: "1:1"}, h: 80pt` → 80×80 (was 0-width invisible).
- **CR-6** ✓ undirected group inside `direction: rtl` root: child `start: parent.start+100pt`
  resolves to x=350 in a 500pt group (right edge −100 −50 width) — inheritance works.
- **CR-7** ✓ rtl derivation string `right = parent.right - 100pt -> 650.0` with parent.right
  750 — numerically consistent (was `+100pt -> 900` vs 1000).
- **CR-8/9** ✓ exact-match `{{ num }}` → `۷` under fa (matches embedded `n = ۷`);
  `digits: arab` → `٧` (U+0667); en stays ASCII.
- **CR-10** ✓ overlay `keepnull: null` with a declared default → binds None
  (`{{ keepnull is none }}` → true), no default resurrection; required-null → ARC-TPL-014
  "required but was provided as null", exit 1.
- **DX-1** ✓ rtl hstack (children 100/150/50pt, gap 10, `main_align: start` in a 600pt row):
  first child at the **right** edge x=500, then 340, 280 — exact hand-computed mirror.
- **DX-2** ✓ repeat inside an hstack: no ARC-LAY-040; identical-constraint repeat in an
  absolute group still warns; hint and `explain` entry rewritten and now accurate
  ("does not fire inside a stack … per-item expressions").
- **DX-3** ✓ default name `prov.square.fa.png` — locale segment present (edge case → RR2-4;
  README drift → RR2-6).
- **DX-4** ✗/✓ four-layer construction with a distinct value per layer: defaults <
  locale-inline < user-base ✓, sidecar wins ✓, required tracking ✓ — but inline vs user-base is
  **inverted** (→ **RR2-1**); sidecar inference reported, inline not (→ RR2-3).
- **DX-5** ✓ README constraints section verified **by running its examples**: sibling anchors,
  logical start/end with rtl offset flip, `aspect(1:2)` sugar (80×160), min/max clamps incl.
  stack shares, full `fit:` schema, `wrap: true` → located ARC-LAY-056, `max_lines` capping
  `fit_content` height (48pt not 168pt) — all accurate. Layering paragraph is wrong (RR2-1) and
  the intro's default-name line stale (RR2-6).
- **CR-11 (P3 spot)** ✓ patch field-edit through a repeat wrapper applies; `nodes.root`
  addressable (existing fields — RR2-11); per-item constraint expressions position chips
  y=10/40 exactly.
- **CR-12 (P3 spot)** ✓ stack fill clamps apply (`max: 50pt` honored; redistribution gap →
  RR2-8).
- **CR-13 (P3 spot)** ✓ 20pt-high truncate box → ARC-LAY-051 warning instead of a bare "…"
  (mislabeled number → RR2-5).
- **CR-14 (P3 spot)** ✓ anchor to a 45°-rotated square's `bottom+10pt` lands at 230.71
  (AABB bottom 220.71 + 10); paint bounds 79.29/141.42 exact.
- **CR-17 (P3 spot)** ✓ `!delete` tag removes; plain string `"!delete"` renders literally.
- **DX-6 (P3 spot)** ✓ op typo echoed ("got keys: 'insert_afterr', 'node'"); ARC-IR-011/012
  explain entries now describe aspect and the size keywords correctly.
- **DX-10 (P3 spot)** ✓ sidecar passed as `--data` → hint: "This file looks like a locale
  overlay ('data.fa.yaml'); pass the base data file ('data.yaml') with '--locale fa' instead."
- **DX-14** ✓ `arcavex --version` → `arcavex 0.1.0.dev0`, exit 0.
- **Seeded failures** ✓ cycle → ARC-LAY-052 "a -> b -> a" exit 1; `overflow: error` →
  ARC-LAY-050 with measured extents, exit 1.

## ADR-0002 assessment

Coherent, well-argued, and complete as a document: all three decisions state the rule, the spec
basis, and the consequences; Decisions 1 (direction inheritance) and 2 (null-as-value) are
implemented exactly to the letter — verified by independent fixtures including the
"explicit null with a default present" and "required null" corner cases. Decision 3 is the
problem: the implementation contradicts its central ordering claim (RR2-1) and its inference-
reporting claim (RR2-3). The ADR itself needs no rewrite if the code is fixed to match.

## Remediation scrutiny pointers (as requested)

- **`_FIT_WIDTH_MARGIN`** — not masking a quantization bug (quantization cannot produce a
  0.5pt error); effect is benign, deterministic, and capped at +0.5pt on intrinsic widths, but
  the comment's causal claim is wrong and the magnitude eye-tuned → RR2-7.
- **title fit_content×shrink×max_lines** — behaves correctly on all six renders (single-line
  title hugged, rhythm even); the interaction resolves shrink first, then hugs — no anomaly
  found. The same machinery on *subtitle* is what clips a4/en → RR2-2.
- **a4 eye-tuned patch values** — venue is one line in both locales (en now matches fa);
  title holds one line at 48pt; page balance acceptable. The patch simply missed the subtitle
  → RR2-2.

## Visual verdicts (all six rendered fresh at `d8fadc3` and viewed, + debug)

| Format | en | fa | Notes |
|---|---|---|---|
| square | **pass** | **pass** | fa is a true mirror; accent flipped +4 (DX-13); ۱۵/۱۷:۰۰ digits |
| story | **pass** | **pass** | DX-11 resolved: taller hero + bottom-anchored footer band (rule/wordmark/localized CTA) closes the frame in both locales |
| a4 | **pass with caveat** | **pass** | venue one line both locales (DX-12 fixed); en subtitle clipped mid-sentence → RR2-2 |

Debug overlay (fa square): DX-9 resolved — coincident labels deconflicted with offsets and
distinct colors (datebox/date-frame/date-lines all legible), corner labels clamped on-canvas,
baselines/safe-area intact; debug render byte-identical across two runs.

## Regression hunt (adversarial probes, none previously exercised)

1. **Nested hstack inside a rtl hstack** — inner mirrors exactly once (i1 at inner's right
   edge, x=530=590−60); no double-flip. Exact.
2. **`main_align: space_between` under rtl** — 100/50/50 in 500pt → gaps exactly 150,
   first at right (x=400), last at left (x=0). Exact.
3. **`main_align: end` under rtl** — packs at the left edge (x=0). Correct mirror.
4. **Stack children overflowing the box under rtl** — spills out the *left* (x=−50), the
   correct mirror of ltr overflow; no crash, no warning (acceptable).
5. **Overlap reporting** — partial sibling overlap reported with the exact intersection rect;
   containment suppressed even for non-backdrop pairs (→ RR2-9). `free_regions` populated
   (CR-15).
6. **Patch/`!delete`/null interplay across layers** — surfaced RR2-1 (the one real hit).

## Deferral judgments

- **`line_height` placeholders** — accept. Fields are inert, the invented 1.2 divisor is gone
  (`_unit_line_height` measures a real single-line paragraph, falls back to 1.2 only on
  degenerate zero-height), the hash-stability rationale for keeping the fields is sound, and
  the ledger row (`IMPLEMENTATION_LEDGER.md` §4.3b) records the binding-level blocker
  (skia-python 144 StrutStyle). Minor hint inconsistency → RR2-12.
- **DX-15 (zero-area text warning)** — accept. The stated cost (layout-time size resolution)
  is real, `overflow: clip` makes the result well-defined, CR-13 covers the truncate flavor,
  and `layout inspect` now reports the clipped state with measured extents (verified on RR2-2),
  which is the promised net.

## Carried P3s for the Phase 3 backlog

RR2-3 .. RR2-12 above, plus (standing from earlier phases): CR-13/phase-1 canonical float form
(due by Phase 4). RR2-1 and RR2-2 are not carried — they block acceptance.

## Commands run

```powershell
.venv\Scripts\python.exe -m pytest tests -q            # 305 passed
.venv\Scripts\python.exe -m ruff check .               # clean
.venv\Scripts\python.exe -m mypy --strict src/arcavex/kernel   # clean
.venv\Scripts\lint-imports.exe                         # 3 kept
# fixtures/probes under outputs-tmp/rr2/: prov/ (CR-1/2/8/9/10, DX-3/4), rtl/ (DX-1, CR-6/7),
# aspect.yaml (CR-4/5), rot_fill.yaml (CR-14, CR-12), deltest/ + ordertest/ (RR2-1),
# repeat_stack/abs (DX-2), patch_typo/patch_repeat (CR-3/11), trunc_short + ls_*.yaml (CR-13),
# readme_claims/wrap_true/ml.yaml (DX-5/7), adv1/adv2.yaml (regression hunt),
# 6 ipen renders + debug (viewed), det1/det2 + dbg2 byte-compares
```

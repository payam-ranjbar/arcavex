# Phase 02 code review — layout, text stack, locales, masks, inspection

Reviewed commit: `157b799` (diff base `b5ecdf8`). Reviewer: adversarial code review agent
(execution-verified). Probe artifacts under `outputs-tmp/review2/`.

## Verdict

**REQUEST CHANGES.** The core engineering is strong — anchor/stack math is exact against hand
computation, patches apply in the right order with correct overlay-merge semantics, masks are
pixel-correct, RTL/BiDi rendering (including ellipsis placement and Latin-in-Farsi single-paragraph
shaping) is right, determinism and the pre-phase-2 byte-identical regression both hold, and every
seeded failure produces a located diagnostic with the correct exit code. But two required Phase 2
behaviors are missing/wrong (CR-1, CR-2), and a cluster of P2 semantic divergences in the solver,
locale digits, and patch/overlay semantics need fixes or explicit adjudication.

## Gates (all executed)

| Gate | Result |
|---|---|
| `pytest tests -q` | 277 passed, 0 failed |
| `ruff check .` | clean (`ruff format --check` is not clean, but was already not clean at `b5ecdf8` — pre-existing, not a phase-2 regression) |
| `mypy --strict src/arcavex/kernel` | clean (12 files) |
| `lint-imports` | 3 contracts kept, 0 broken (kernel purity preserved) |

## Findings

### P1 — required Phase 2 behavior missing or wrong

**CR-1 — `template inspect --resolved` (provenance inspection) is not implemented.**
Brief item 3 and spec §4.1.4 require `arcavex template inspect --resolved --format F --locale L`
to report final values with the originating layer. `overlays.PatchLog` is populated
(`compiler.py:145,634,648`) and my probe confirms it records the right layers in the right order
(`format:patched` ops then `locale:fa` ops), but nothing ever reads it: `template_inspect` in
`clients/cli.py:455` has no `--resolved`, `--format`, or `--locale` options, and no facade/authoring
path surfaces provenance. Resolution order itself is correct (verified: value set at template →
format patch → locale patch; locale wins, `probe_compile.py`), but it is not inspectable, which is
the actual deliverable.
*Required fix:* implement `--resolved` reporting final values + introducing layer (template /
format:X / locale:Y), driven by the existing PatchLog plus compiled values.

**CR-2 — unknown typography/style fields pass validation silently.**
Spec §4.3 and the brief: "Unsupported typography fields still fail validation." Only
`line_height` is special-cased (`compiler.py:1912`). Probe: a text node with
`style: {…, font_sze: 99pt, kerning: tight}` validates OK (`t_junkstyle`, exit 0) —
`_parse_style` (`compiler.py:1889`) reads known keys and ignores everything else. This also
converts patch-path typos into silent no-ops (see CR-3) and silently drops any misspelled
field (`font_wieght`, `letterspacing`, …), exactly the accepted-but-ignored pattern this
codebase rejects elsewhere.
*Required fix:* reject unknown keys in `style:` (and ideally in node mappings, `fit:`,
`paragraph:`, run mappings) with a located diagnostic.

### P2 — semantics wrong or divergent from spec

**CR-3 — patch `set` with an unknown final segment silently creates the key.**
Spec §4.1.4: "An unknown path is an error." `_do_set` (`overlays.py:139-145`) errors on unknown
*intermediate* segments but blindly assigns the last one. Probe: `set: nodes.x.style.font_sze`
succeeds and produces `style: {fill: …, font_sze: 9pt}`, which the compiler then ignores (CR-2) —
an end-to-end silent no-op for a typo'd patch. `remove` gets this right
(`unknown patch path field 'nope'`). Fix: `set` should require the final key to exist, or at
minimum validate the resulting node; pick one and document it.

**CR-4 — `aspect` derives from the *unclamped* other axis.**
`solver.py:336-351`: w/h are computed, aspect derived, and only then `_clamp` runs. Probe
(`t_aspect`): `h: {value: 100pt, max: 50pt}` + `w: {aspect: "2:1"}` yields **200×50** — the
declared 2:1 ratio is broken by an interaction the author can't see. Expected 100×50 (derive from
the clamped value; then apply the aspect axis's own clamp).

**CR-5 — `aspect` on a stack's cross axis resolves to size 0 with no diagnostic.**
`_cross_size` (`solver.py:286-291`) returns `0.0` for aspect with a comment claiming it is
"resolved in the main pass instead" — it never is. Probe: vstack child `w: {aspect: "1:1"},
h: 80pt` → bounds `(0, 200, 0.0, 80)`: an invisible node, silently. Either resolve cross-aspect
after the main size is known, or reject it with a located error.

**CR-6 — group `direction` does not inherit from the enclosing group.**
`compiler.py:874`: an undirected group gets the *locale* default, never its parent group's
direction. Probe (`t_mixdir`, no locale): a group without `direction` inside an explicit
`direction: rtl` root lays out its children LTR (`n1.x = 20`, not 540). An explicitly-`ltr`
group inside rtl is honored, and the rtl root itself is honored — only inheritance is missing.
"Nearest enclosing group direction" (spec §4.2 logical-edge rule + Appendix A's single
root-level `direction: rtl`) strongly implies nesting should inherit; today an author must
re-declare `direction` on every nested group or the layout silently flips. Adjudicate and
either inherit at compile time or document loudly.

**CR-7 — `layout inspect` anchor-derivation strings are numerically wrong for logical edges
under RTL.** The solver flips a logical edge's offset in reading order (`solver.py:396-397`,
correct), but `_derive_anchors` (`api.py:1043-1045`) prints the raw offset. Probe: node with
`start: parent.start+100pt` in an rtl group reports `right = 'parent.right + 100pt' -> 900.0`
while `parent.right` is 1000 — the printed expression evaluates to 1100, not 900. The brief's
requirement is that derivation strings "match actual math"; they don't for exactly the RTL cases
this phase is about.

**CR-8 — `digits: fa` misses exact-match numeric expressions.**
`render_value` (`expressions.py:638-640`) returns the native value for a scalar that is exactly
one expression, bypassing `_localize_digits`; the compiler then stringifies without digits
(`compiler.py:2136-2140`). Probe: under `--locale fa`, `text: "{{ num }}"` renders ASCII `42`
while `text: "n = {{ num }}"` renders `n = ۴۲`. Same variable, same locale, different digits
depending on whether there is surrounding text.

**CR-9 — `digits: arab` (and `latn`) are accepted by validation and silently do nothing.**
`_LOCALE_DIGITS` allows `en|fa|latn|arab` (`compiler.py:95`), but `_localize_digits`
(`expressions.py:664-668`) implements only `"fa"`, and `locale_digits()` supports only en/fa.
Probe: `digits: arab` → `n = 42`, ASCII, no diagnostic. Implement Arabic-Indic (U+0660–0669)
or reject the value until it exists.

**CR-10 — locale-overlay `null` does not remain a value.**
Spec §4.1.4: "null remains a valid data value and therefore does not mean deletion."
`merge_overlay` keeps the key with `None` (correct), but the variable layer then drops all
None-valued keys (`compiler.py:324`, phase-1 CR-5 behavior) and the declaration loop backfills
the default. Probe: base supplies `keepnull: "supplied"`, `data.fa.yaml` overlays
`keepnull: null` → final value is the *template default* (`{{ keepnull is none }}` → `false`).
Consequence: `null` and `!delete` are indistinguishable, and overlaying null resurrects
defaults. This is a real conflict between phase-1 CR-5 (null ≡ omission for base data) and
§4.1.4 (null is a value in overlays); needs explicit adjudication — as written the spec is
violated.

### P3 — required-quality gaps, sharp edges, doc drift

**CR-11 — patches cannot field-edit nodes under `repeat`/`if`, and cannot address `root`.**
`_search` (`overlays.py:184-200`) returns the *wrapper* mapping for a construct-wrapped id, so
`set: nodes.cond.style.fill` fails with the misleading "unknown patch path segment 'style'"
(the node has `style`; the wrapper doesn't). `remove: nodes.cond` works (removes the wrapper).
Also `set: nodes.root.direction` fails ("no node with id 'root'") because `_search` only scans
`children`. Fix the traversal (descend into `node:` for field ops; include root) or emit an
accurate diagnostic.

**CR-12 — `fill` sizes bypass min/max clamps inside stacks.**
Absolute-mode fill is clamped (`solver.py:351`), but a stack's main-axis fill share
(`solver.py:239,245`) and the cross-axis fill/stretch (`solver.py:286-287`) ignore
`min`/`max`. Spec §4.2/models: clamps apply "on any mode".

**CR-13 — `truncate` collapses to a bare "…" when the box is shorter than one line.**
`_truncate` (`service.py:157-181`) requires each candidate to pass the *height* check too; a
200×28pt box with 20pt Vazirmatn (line ≈ 31pt) fits no prefix, so the entire text is replaced
by "…" (verified visually, `out/fit.png`). With a fitting height the behavior is correct and
the ellipsis lands on the right visual side in both directions (`out/fit2.png`). Consider
truncating on width/max_lines and letting height clip, or warn.

**CR-14 — rotation AABB is not used for sibling anchors or overlap reporting.**
`sib_rects` stores pre-rotation rects (`solver.py:142`) and `_collect_overlaps` uses
`bounds`, not `paint_bounds` (`api.py:1055-1065`). Probe (`t_rot`): a node anchored to a
45°-rotated square's `bottom+10pt` gets y=210 (AABB bottom is 220.7), and no overlap is
reported although the AABBs visibly intersect. Spec §4.2: rotations "contribute their
post-transform AABB to sibling/layout inspection". Paint bounds themselves are correct
(79.289/141.421 for the 45° case, exact). At minimum overlaps should consider the AABB;
anchor semantics need a documented decision.

**CR-15 — `layout inspect` omits two promised fields.** §6.1.1/brief item 5 list "absolute
transform" and "free regions summary"; `LayoutNodeReport` (`api.py:319-333`) carries only
`rotate_deg`, and the only region summary is `covered_fraction` (a single scalar, not free
regions). `paint_bounds` is also pt-only (bounds are pt+px).

**CR-16 — truncation measures with the node's base style, paints with the lead run's style.**
`_truncate`/`_layout_text` (`service.py:157-181,257-269`) rebuild the candidate as a single run
from `req.font_families`/`font_size_pt`, but the solver's `_scale_runs` (`solver.py:703-713`)
emits the truncated text in the *lead run's* style. For multi-run text with differing
fonts/sizes the measured prefix and the painted prefix can disagree; per-run styling is silently
dropped on truncation. Document or fix.

**CR-17 — the plain string `"!delete"` also deletes.** `is_delete` (`overlays.py:48-53`)
matches the string value as well as the YAML tag, so a literal `"!delete"` string value is
unrepresentable in overlays. Match the tag only.

**CR-18 — acceptance-artifact doc drift.** `examples/ipen-bilingual/data.fa.yaml` claims
"day/time keep their numeric values and are shown with Persian digits", but `time` is
*overridden* with hardcoded Persian digits (`"۱۷:۰۰"`) precisely because the digit policy
cannot touch string values and expressions cannot see the active locale. The fa poster's time
digits come from data, not the locale system. Correct the comment (and consider exposing the
active locale to expressions so `locale_digits(time, locale)` is writable).

**CR-19 — `line_height` deferral leaves dead fields and a mismatched approximation.**
Rejecting `line_height` with located ARC-TPL-053 is honest, but §4.3 lists line height in the
v1 schema — this needs a tracked ticket (ledger was not updated for phase 2 at all). Meanwhile
`Style.line_height`/`ResolvedText.line_height` are always `None`, and `_metrics`
(`service.py:324-331`) estimates line count with `size * (line_height or 1.2)` — an invented
divisor that under/over-counts for fonts whose natural line height isn't 1.2 (this is why the
28pt-box truncate in CR-13 surprises). Document the approximation per the brief.

Minor notes (no action required to accept): locale font override produces duplicate families
(`Inter→[Vazirmatn, Inter]` on `[Inter, Vazirmatn]` gives `Vazirmatn, Inter, Vazirmatn` —
harmless); `_measure_text` resolves auto-direction with a hardcoded `"ltr"` group dir
(`solver.py:547`) unlike `_resolve_text`; debug-overlay labels of coincident nodes overprint
(datebox/date-frame); `gutter: 0` and `angle` of any float are accepted for diamond_grid
(reasonable — negative/zero cell, negative gutter, junk angle, %, and unknown params all fail
with located ARC-FX-902 at compile time, verified).

## What was verified good (execution evidence)

- **§4.2 math:** 3-deep sibling chain, hstack fill-sharing/gap/padding/cross-center, vstack
  space_between + stretch all match hand-computed values exactly (`probe_layout.py`).
  1/1024pt snapping holds. Under-/over-constrained → ARC-LAY-030/031; stack child with anchors
  → ARC-LAY-054; aspect-on-both-axes → ARC-LAY-055; cycle → ARC-LAY-052 naming the full cycle
  (`a -> c -> b -> a`), located; unknown sibling ref → ARC-LAY-053.
- **Logical directions:** rtl start/end resolution and reading-order offset flip correct in the
  solver; explicit nested ltr-inside-rtl honored (CR-6 covers the inheritance gap).
- **Expressions in constraints** (`parent.top+{{ … }}pt`) work, including inside repeat with
  `loop.index`, and intra-repeat sibling refs suffix correctly (`label[x]`/`tail[x]`).
- **§4.3:** shrink non-convergence → ARC-LAY-051 warning with measured values; `overflow: error`
  → ARC-LAY-050, exit 1; missing glyph (U+1F389) → ARC-RND-011 warning naming code point + chain;
  NFC composed vs decomposed input → byte-identical PNGs; Latin-inside-Farsi runs shape in ONE
  paragraph with per-run family/weight/color (verified visually); RTL truncate places the
  ellipsis on the correct visual side (left for rtl, right for ltr).
- **§4.1.4:** ops exactly set/remove/insert_before/insert_after; unknown verb, unknown node,
  unknown mid-segment, remove-unknown-field all located ARC-TPL-092; file-order application
  including set→remove→re-insert of the same id; overlay merge (nested mapping merge, scalar
  replace, list-replace-whole, `!delete`) correct at the merge layer; resolution order
  template → format patch → locale patch confirmed with a triple-set probe.
- **Locales:** direction default per locale applied; `digits: fa` maps interpolated numerics and
  leaves constraint strings untouched (`40pt` safe, verified); font overrides swap stacks;
  sibling `data.<locale>.yaml` overlay applied and reported as `data_overlay` inference;
  undeclared locale → located ARC-TPL-100, exit 1.
- **Masks:** diamond_grid pixel-verified (cell centers show content, gutter midpoints show
  background, at computed lattice positions); circle mask on a group clips children
  (pixel-verified); invalid params → located ARC-FX-902 at compile.
- **Inspect:** JSON versioned (`response_version: 1`); ltr derivation strings match math
  numerically; overlaps reported including a constructed one (`date-frame ∩ date-lines`);
  px = pt·dpi/72 exact for every node at a4@300dpi (canvas 2480×3508).
- **Determinism/regression:** `--debug` twice → byte-identical; debug ≠ non-debug; non-debug
  render byte-identical to the same command's separate run; hello-poster and the
  `template new` scaffold render **byte-identical to `b5ecdf8`** (baseline built from a git
  worktree, engine code verified loaded from the worktree).
- **ipen-bilingual:** all 6 format×locale combinations render; fa square/story/a4 show correct
  RTL flow, shaped Farsi, fa digits (۱۵, ۱۷:۰۰), masked hero, rotated accent; en variants
  correct LTR. Story format has generous empty bottom space — composition judgment left to the
  DX review.
- **Carry-overs:** RR1-1 (ARC-TPL-061 hint/explain/README all describe the wrapper-group form;
  test proves the suggested form compiles), RR1-2 (`[if]`/`[repeat]` tags render literally,
  tested), RR1-3 (verified live: `inferred: output=…` prints before the pipeline runs).
- **Architecture:** kernel imports clean (lint-imports); no second shaper — all measurement
  through `TextService` (grep: skia imports only in backend_skia, masks_core, export_raster,
  text service, doctor; no measureText/HarfBuzz elsewhere); MaskGenerator conforms to the
  `Path2D` structural protocol; snapshots have a documented `ARCAVEX_UPDATE_SNAPSHOTS=1`
  update mechanism.

## Commands run

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m ruff check .; ruff format --check .
.venv\Scripts\python.exe -m mypy --strict src/arcavex/kernel
.venv\Scripts\lint-imports.exe
.venv\Scripts\python.exe outputs-tmp\review2\probe_layout.py     # anchor/stack/aspect/rotation math
.venv\Scripts\python.exe outputs-tmp\review2\probe_compile.py    # patches, overlays, digits, locales
.venv\Scripts\python.exe outputs-tmp\review2\probe_patch2.py     # patch final-segment semantics
.venv\Scripts\python.exe outputs-tmp\review2\probe_mask.py       # mask pixel sampling + param errors
.venv\Scripts\python.exe outputs-tmp\review2\probe_misc.py       # null overlay, px/pt, overlaps
# + CLI probes: seeded failures (exit 1/3), NFC byte-compare, debug determinism,
#   b5ecdf8 worktree baseline byte-compare (hello-poster, scaffold), all 6 ipen renders (viewed)
```

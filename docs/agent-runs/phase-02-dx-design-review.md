# Phase 02 DX & design review — layout, text, locales, masks, inspection

Reviewed commit: `157b799`. Reviewer: design & developer-experience agent. Method: authored a
new bilingual speaker-card template from scratch with the README as the only guide
(`outputs-tmp/dx2/speaker-card/`), rendered and visually inspected all 6 ipen-bilingual combos
plus 4 speaker-card combos (`outputs-tmp/dx2/*.png`), ran a diagnostics sweep
(`outputs-tmp/dx2/diag/`), and audited the §6.3 contract. The phase-02 code review was read
only after these impressions were formed; its findings are referenced as CR-n, not re-litigated.

## Verdict

**REMEDIATE.** The engine under the surface is genuinely pleasant to author against — located
errors with hints nearly everywhere, readable cycle messages, forward sibling references that
just work, honest RTL mirroring of anchors/text/digits/fonts. But the phase's own headline —
bilingual mirroring — has a hole (stacks do not mirror, DX-1), the tooling actively misleads
authors away from the phase's shipped features (DX-2), the default output name violates the
§6.3 contract and silently overwrites across locales (DX-3), the locale data overlay has a
silent two-source precedence trap (DX-4), and the README documents almost none of the new
constraint surface, and is wrong about part of it (DX-5). None of these is deep; all of them
hit a real author in the first hour.

## Findings

### P1

**DX-1 — hstack/vstack do not mirror under RTL: packing order and `main_align` ignore
direction.** *Did:* put three topic chips in a `layout: hstack` group, rendered `--locale fa`
(root direction rtl); then a minimal probe with an **explicit** `direction: rtl` on the hstack
(`outputs-tmp/dx2/diag/rtlstack.yaml`). *Happened:* the first child packs at the LEFT edge in
both cases (`first shape (0.0, …)` with `main_align: start`); the row's own `start:` anchor
mirrors to the right edge, so the trailing gap lands on the wrong side and the last chip
collides with the right-aligned footer in fa (`outputs-tmp/dx2/speaker-fa-square.png`, the
تایپ chip). The fa poster's chips also read in LTR order — قطعیت first-from-left instead of
first-from-right. *Must change:* stacks resolve main-axis order and `main_align: start|end`
through the group's direction (spec §4.2: logical directions resolve "through the enclosing
group's direction"). Distinct from CR-6 (direction inheritance) and CR-7 (derivation strings):
here the group's direction IS rtl and the stack still packs LTR. Note the golden case only
exercises a *vertical* stack, so nothing in CI catches this.

**DX-2 — ARC-LAY-040 fires falsely on repeats inside stacks, and its hint + explain entry
describe a build that no longer exists.** *Did:* followed the README's own recommendation:
"put them in a `layout: hstack`/`vstack` group" for repeated siblings. *Happened:* every
validate/render emits `WARNING ARC-LAY-040 … they resolve to the same bounds and will overlap`
with hint "Constraint values are static in this build … or await layout stacks (Phase 2)" —
while the render proves the stack lays them out correctly. `explain ARC-LAY-040` doubles down:
"no expressions inside constraints, no layout stacks yet". Both claims are false in this build
(expressions in constraints work — verified with `loop.index` offsets — and stacks shipped).
*Must change:* suppress the warning when the expanded siblings are children of a stack (or when
their post-expansion bounds actually coincide, which is what the message claims to know);
rewrite the hint and catalog entry. A first-hour author cannot distinguish this false alarm
from the real overlap warnings they should trust; it poisons confidence in the whole
diagnostic channel.

**DX-3 — default output name omits the locale: `--locale fa` silently overwrites the en
render.** *Did:* `render … --format square --locale fa` with no `-o`. *Happened:* output is
`ipen-bilingual.square.png` — the same path as the en render; the JSON `inferred.output`
confirms it. §6.3 line 790 specifies `<template>.<format>[.<locale>].<ext>`. *Must change:*
include the locale segment whenever `--locale` is given. This is a release-criterion violation
and a data-loss footgun in exactly the render-both-locales loop the bilingual poster is for.

**DX-4 — two silent sources of locale data overlay; the convention sidecar outranks the
declared one.** *Did:* declared translations inline under `locales.fa.data:` (the only form the
top-level README/spec mention — and the ARC-TPL-099 hint steers you to). A `data.fa.yaml` also
sat next to my `data.yaml`. Later I edited the inline `bio` and re-rendered. *Happened:*
nothing changed — the auto-inferred sidecar overlay wins over the template's inline mapping,
and with `--quiet` the only breadcrumb (`inferred: data_overlay=data.fa.yaml`) is suppressed.
Ten minutes of "why is my edit ignored". The top-level README never documents the
`data.<locale>.yaml` convention at all; only the example's README mentions the merge, and no
document states the precedence between the two. *Must change:* document the sidecar convention
and its precedence in the README; emit a warning (not just an inference note) when the inline
`locales.<l>.data` and a sidecar overlay both define the same key — per §6.3, ambiguity should
produce a diagnostic, not a silent choice.

**DX-5 — the README does not teach the constraint system this phase shipped, and contradicts
it.** *Did:* authored from the README alone, as §6.3 assumes. *Happened, verbatim:*
- "Anchors reference **a parent edge**" — sibling anchors (`hero.bottom+26pt`) are never
  documented; I learned the syntax from the example template.
- "`{{ }}` expressions are **not** evaluated inside constraints" — false; they are (and the
  repeat note two sections earlier says so — the README contradicts itself).
- `aspect` appears once, name-only, in *Known limitations*. The syntax took three guesses:
  `h: aspect(1:1)` (the spec §4.2's own literal form!) → ARC-IR-011 whose hint doesn't mention
  aspect; `size: {w: 34%, aspect: "1:1"}` → ARC-LAY-032, whose hint finally reveals
  `{aspect: 'W:H'}`.
- `min`/`max` size bounds, the `fit:` block schema, and `overflow` being a modifier (not a
  policy — spec §4.2 says `overflow(clip|allow|error)`, the build rejects `policy: overflow`)
  are all undocumented.
*Must change:* rewrite "Constraints and anchors" to cover sibling refs, logical `start`/`end`,
`{aspect: "W:H"}`, min/max, and the full `fit:` schema; delete the false expressions sentence.
The features are good; the map to them is missing.

### P2

**DX-6 — diagnostic/catalog mismatches around aspect.** ARC-IR-011's hint ("Use a number with
an optional unit: px, pt, mm, or %") omits `fill`, `fit_content`, and `aspect` — it fires on
the exact spec-literate guess `aspect(1:1)` and steers away from the feature. `explain
ARC-IR-012` says "Invalid percent size … Use a value like '62%'" but the CLI emits ARC-IR-012
for invalid *aspect* strings ("invalid aspect 'banana'"), so explain describes a different
failure than the one you hit. Also ARC-TPL-092 for an op typo doesn't echo the offending key
(`insert_afterr`), just "needs exactly one of set/remove/…". Align hints and catalog with the
codes' actual uses.

**DX-7 — `max_lines` is a no-op when `h: fit_content`.** *Did:* bio with
`fit: {policy: wrap, overflow: clip, max_lines: 2}` and `size: {…, h: fit_content}`.
*Happened:* the Farsi bio rendered all 3 lines (`speaker-fa-story.png`, pre-fix). fit_content
sizes the box to the *full* text, so there is never anything to clip and max_lines silently
does nothing. *Must change:* cap the fit_content measurement at max_lines (or reject/warn on
the combination). Related to the paragraph-metrics approximation (CR-19) but this is the
authoring-surface consequence.

**DX-8 — `layout inspect` overlap reporting is signal-buried.** My real bug (`topics-row ∩
footer`) was reported — as line 11 of 11, under `background ∩ <every node>` (a full-bleed
fill overlapping everything is trivially true) and intentional parent-fill pairs
(`chip-bg ∩ chip-label`). *Must change:* exclude or de-rank overlaps where one node is a
fill-both-axes backdrop or an ancestor-fill, and consider flagging text∩text /
cross-branch overlaps first — those are the ones that are almost always bugs. (The engine
gave zero render-time signal when the fa locale's taller line boxes pushed my chips into the
footer; inspect is the only net, so its signal-to-noise matters.)

**DX-9 — debug overlay labels are illegible in dense regions.** In
`outputs-tmp/dx2/speaker-en-square-debug.png`: the three chip groups produce red-on-red
overprinted label stacks (`chip-bg[Determinism]` over `chip-label[Determinism]` over the chip
text), the `footer` label is entirely hidden under the chip boxes, and the `background` label
is clipped at the canvas corner. The overlay is excellent for sparse layouts (the dead space
in my 120pt name box was instantly visible; baselines and safe-area are genuinely useful) but
fails exactly where you need it — collision zones. *Must change:* deconflict labels (stack
with offsets/leader lines), clamp labels into the canvas. (The code review's minor note
mentions overprint; this is the author-facing consequence with evidence.)

**DX-10 — overlay files masquerade as data files and fail confusingly.** *Did:* the natural
first read of `examples/ipen-bilingual/data.fa.yaml` is "the Farsi data file", so I passed it
as `--data … --locale fa`. *Happened:* `ARC-TPL-014 Variable 'day' is required but was not
provided` — nothing says the file is a *partial overlay* meant to ride on `data.yaml`.
*Must change:* when a `--data` file's name matches the `data.<locale>.yaml` overlay convention,
say so in the error hint ("this file looks like a locale overlay; pass the base data file and
--locale fa instead").

**DX-11 (design) — ipen story reads unfinished, not intentional, in both locales.** Content
ends at ~70% of the 1080×1920 canvas and the bottom ~550px is a featureless navy slab with no
closing element — no footer, no brand mark, no gradient, nothing bottom-anchored to close the
frame. At thumbnail size the poster looks vertically mis-cropped. The square composition is
genuinely good, which makes the story read like the square poured into a taller glass. The A4
patch (`hero h: 38%`) proves the mechanism exists; story got no patch at all. *Must change:*
give story a patch (scale hero/type, or add a bottom-anchored element). "Intentional
whitespace" needs an element that demonstrates the intent; my speaker-card story patch
(`outputs-tmp/dx2/speaker-card/template.yaml`, `formats.story.patch`) shows ~10 lines suffice.

### P3

**DX-12 (design) — ipen A4/square rhythm nits.** (a) en A4: `venue` wraps to a second line
("— Collision / Space"), leaving a bottom margin visibly tighter than the generous side
margins; fa A4 (one-line venue) is the better-balanced page — the two locales' pages don't
match. (b) All formats: `title` is a single line inside a fixed `h: 116pt` box, so the
title→subtitle gap is ~2× the accent→title gap — a visible rhythm break, worst at A4. The
fixed-height-box-plus-shrink_to_fit pattern invites this (I hit the identical trap with my
name box; the `--debug` overlay is what exposed it in both cases).

**DX-13 (locale polish)** — the rotated accent keeps `rotate: -4` under rtl (a mirrored
composition would flip to +4; debatable, but a designer would flip it); fa `time` is
hand-localized in the overlay rather than by the digit system (CR-18 — reference, the
half-translation risk it creates is real: an author editing `data.yaml`'s time will ship an
en time into the fa poster silently).

**DX-14 — no `arcavex --version`.** Exit 2. `doctor` is the only way to learn the engine
version; a `--version` flag is table stakes for bug reports.

**DX-15 — text in a 0-height box renders silently empty** with `overflow: clip` (exit 0, no
diagnostic). Defensible (clip means clip), but a zero-area text box is nearly always a
mistake; a validate-time warning would be cheap.

## Friction log (chronological, as hit)

1. `arcavex --version` → exit 2, "No such option". (DX-14)
2. README teaches only parent-edge anchors; opened the example to learn `hero.bottom+26pt`
   and logical `start`. (DX-5)
3. Guessed `locales.fa.data: data.fa.yaml` (a path) → ARC-TPL-099, good located hint ("write
   'data:' as a mapping"), inline mapping worked. Later discovered the path form *effectively
   exists anyway* via the silent sidecar convention. (DX-4)
4. `h: aspect(1:1)` (spec's own syntax) → ARC-IR-011, hint doesn't mention aspect. Guess 2:
   `size: {w: 34%, aspect: "1:1"}` → ARC-LAY-032, whose hint finally teaches
   `{aspect: 'W:H'}`. Three tries for one feature. (DX-5/DX-6)
5. `line_height: 1.5` → ARC-TPL-053 "not supported in this build". Honest fail-loud, but spec
   §4.3 lists line height in the v1 schema. (CR-19)
6. First valid render: ARC-LAY-040 warns my hstack chips "will overlap"; the PNG shows them
   laid out perfectly. Warning re-fires on every subsequent render of a correct template. (DX-2)
7. Real bug (chips ∩ footer): `layout inspect` found it — buried at the bottom of 11 overlap
   lines, 10 of them noise. `--debug` made the name-box dead space obvious. (DX-8/DX-9)
8. Forward sibling anchor (`bottom: footer.top-28pt`, footer declared later) worked first try.
   Genuinely impressed.
9. fa render: locale-taller line boxes silently pushed chips into the footer — no render-time
   signal, found only by eyeballing the PNG. (DX-8)
10. Edited inline `locales.fa.data.bio`; re-render unchanged — sidecar `data.fa.yaml` outranks
    it and `--quiet` hides the inference line. (DX-4)
11. Passed `data.fa.yaml` as `--data` for ipen → "Variable 'day' is required". (DX-10)
12. fa bio rendered 3 lines despite `max_lines: 2`. (DX-7)
13. Default output name for `--locale fa` identical to en → overwrote my en render. (DX-3)

## Visual-quality matrix (every PNG viewed)

| Template | Format | Locale | Verdict | Notes |
|---|---|---|---|---|
| ipen-bilingual | square | en | **pass** | Strong: masked hero, clear hierarchy, good margins, holds at thumbnail |
| ipen-bilingual | square | fa | **pass** | True mirror (accent, title, datebox), ۱۵/۱۷:۰۰ digits, Vazirmatn/Estedad correct |
| ipen-bilingual | story | en | **concerns** | Bottom ~28% empty slab; reads top-anchored/unfinished (DX-11) |
| ipen-bilingual | story | fa | **concerns** | Same; mirroring itself correct |
| ipen-bilingual | a4 | en | **concerns** | Venue 2-line wrap → bottom margin tighter than sides; title-box dead space (DX-12) |
| ipen-bilingual | a4 | fa | **pass** | Best-balanced page; minor title-gap rhythm nit |
| speaker-card | square | en | pass | (own template, after fixes) |
| speaker-card | square | fa | pass* | *chips in LTR order — engine DX-1, not authorable around within a stack |
| speaker-card | story | en | pass | format patch fills the frame; modest gap above footer |
| speaker-card | story | fa | pass* | *DX-1 chip order |

## Diagnostics sweep results

All probes under `outputs-tmp/dx2/diag/`. Quality is high across the board:

- `overflow: error` → ARC-LAY-050, exit 1, message includes measured vs box extents
  (198.8×145.0pt into 200.0×40.0pt). Excellent.
- Non-convergent shrink → ARC-LAY-051 **warning** with measured values, render proceeds —
  matches spec's "located diagnostic with measured values".
- Anchor cycle → ARC-LAY-052 "Sibling anchor cycle: a -> b -> a" — the cycle is spelled out
  and readable. Best-in-class error.
- Stack child with anchors → ARC-LAY-054, hint says exactly what to delete.
- Aspect on both axes → ARC-LAY-055; junk aspect string → ARC-IR-012 with 'W:H' example
  (but see DX-6 catalog mismatch).
- Bad mask params → ARC-FX-902 naming the field ("cell: Input should be greater than 0" —
  pydantic phrasing leaks, still clear); unknown mask → ARC-FX-901 **listing the registered
  masks**. Unknown locale → ARC-TPL-100 **listing declared locales**. Both model citizens.
- Patch on unknown id / op typo → located ARC-TPL-092 (typo'd verb not echoed — DX-6).
- 0-height text box → silent success (DX-15).
- ARC-LAY-040 false positive → DX-2.

## explain audit (codes hit this phase)

Substantive and non-circular: ARC-LAY-050/051/052/054/055, ARC-TPL-099/100, ARC-FX-902 — each
explains the *mechanism* and gives a real fix. Two failures: ARC-LAY-040's entry asserts the
build has "no expressions inside constraints, no layout stacks yet" (both shipped this phase —
DX-2), and ARC-IR-012's entry describes percent sizes while the code fires for aspect strings
(DX-6). ARC-TPL-099's "even though locale application is Phase 2" phrasing is now stale.

## §6.3 audit — new commands and flags

- **Inference reporting: good.** `inferred: data_overlay=data.fa.yaml` and
  `inferred: data=preview_data` print in human output and appear as the `inferred` object in
  `--json`. (But the sidecar pickup deserves a stronger signal when it shadows inline locale
  data — DX-4.)
- **JSON versioning: good.** `response_version: 1` on render, validate, `layout inspect`,
  `template inspect`, `explain`, doctor. Diagnostics carry code/severity/message/source
  (file+keypath+line)/hint — the AI workflow (§6.3 "correct from structured diagnostics") is
  fully served; I never needed to scrape console output.
- **`template inspect --json`** lists functions with names/signatures as promised.
- **`--resolved` is absent** — `template inspect` has no `--resolved`, `--format`, or
  `--locale` (CR-1 owns this; from the DX side it means the DX-4 precedence trap has no
  inspection escape hatch either — the tool that would have answered "where did this value
  come from?" doesn't exist).
- **Default naming: violated** — locale segment missing (DX-3). Format segment and
  report-before-render both work.
- **Exit codes** matched the README table in every probe (0 warnings-only, 1 validation, 2
  usage).

## What impressed

- **Located errors with hints are the norm, not the exception** — including inside format
  patches, locale blocks, and mask param schemas. The hints that enumerate valid options
  (registered masks, declared locales) are exactly right.
- **The cycle message** (`a -> b -> a`) and the **overflow/shrink messages with measured
  numbers** are better than most production layout engines ship.
- **Forward sibling references** resolve regardless of declaration order — no manual
  topological ordering, and the cycle detector catches genuine loops with a readable message.
- **Expressions inside constraint values** (incl. `loop.index` arithmetic) work smoothly —
  the feature is better than its own warnings/docs claim it is.
- **RTL is a real mirror where implemented**: logical anchors flip, `align: start` text
  right-aligns, Persian digits apply to interpolated numbers, locale font overrides re-stack
  per family. The fa square poster is a legitimately convincing artifact.
- **`layout inspect`'s anchor-derivation lines** (`v: top = photo.bottom + 40pt → 463.4pt`,
  `h: — = positioned by hstack`) read like a good teacher; diagnosing my collision took
  seconds once I found the signal.
- **The `--debug` overlay's** baselines and safe-area rectangle exposed my dead-space mistake
  instantly (label collisions aside).
- `template new` → render loop from Phase 1 still holds; the compile pipeline never once
  produced an unlocated or internal error during ~40 deliberately broken inputs.

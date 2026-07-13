# Phase 01 DX & design review — authoring loop (commit 1004936)

Reviewer: Fable 5, working as a template author for a full session under `outputs-tmp/dx1/`.
Method: scaffold → evolve into a real event card (locale_digits date, tag list, conditional
footer) using only README + scaffold README + error messages; live watch session with seeded
errors; inspect/split/doctor/explain; a ten-case new-failure-mode sweep; §6.3 line-by-line
audit; aesthetic judgment of rendered output. The existing code review
(`phase-01-code-review.md`, CR-n) was read only after all impressions were formed; its
findings are referenced, not re-litigated.

## Verdict: REMEDIATE (narrow)

The loop itself is excellent — 190 ms save-to-preview against a 2 s budget, error recovery
that never loses the last good image, and diagnostics that are consistently located and
usually genuinely helpful. The remediation case is about the gap between what Phase 1 ships
and what an author can actually discover and use: the flagship structural construct
(`repeat:`) silently produces unusable output in its most natural use, and nothing an author
can reach (README, scaffold, explain) teaches the Phase 1 feature set at all. Fix DX-1 and
DX-2 (plus the code review's CR-1/CR-2, already required) and this phase is an accept.

## Findings

### DX-1 (P1) — `repeat:` renders all items on top of each other, silently
**Did:** Followed the obvious path for a tag row: `repeat: "{{ tags }}"` with a per-item
offset `left: "parent.left + {{ 64 + loop.index * 240 }}px"`.
**Happened:** ARC-LAY-012 "invalid offset" (correctly located, but the hint — "Offsets look
like '+20px'" — never says expressions are not evaluated inside constraints). Falling back to
a static anchor, the render **succeeds with exit 0** and stacks all three tags on the same
point into unreadable glyph soup (`outputs-tmp/dx1/evolve2.png`). No warning, though every
expanded node has byte-identical constraints. Since Phase 1 has no stacks and constraints
take no expressions, there is **no way to lay out repeated siblings at all** — `repeat:` ships
with keys, caps, nesting and stability warnings, yet cannot produce a visible list. The prior
authoring session hit the identical wall independently (see the workaround comment in
`outputs-tmp/dx1/event-card/template.yaml`).
**Must change:** at minimum, emit a warning when a `repeat` expands >1 node with identical
resolved constraints ("repeated items will overlap; per-item layout arrives with stacks
(Phase 2)"), and say "expressions are not evaluated in constraints" in the ARC-LAY-012
hint/explain entry. The better design answer is to let anchor offsets take expressions (the
evaluator, budget, and located errors all exist) or pull minimal `vstack`/`hstack` forward —
otherwise Phase 1's headline feature demos as a bug.

### DX-2 (P1) — no reachable documentation teaches the Phase 1 feature set
**Did:** Worked strictly from README + scaffold README + error messages, per the intended
authoring contract.
**Happened:** The top-level README still describes Phase 0: "`repeat`/`if` … are later phases
and are rejected with a 'not supported in this build' diagnostic" and lists only
`len/upper/lower/format` (README.md:38-39, 63) — both now false. The scaffold uses no
`repeat:`, `if:`, or function beyond `default()`, and its README never mentions `template
check/split`, `doctor`, or `explain`. The only place `repeat:`/`as:`/`key:` syntax exists is
the design spec. I authored the constructs from spec knowledge; a real author cannot.
**Must change:** update README's template-anatomy section to Phase 1 truth (structural
constructs, all nine functions, split layout, new commands), and make the scaffold teach at
least one `if:` (it is fully usable today) plus a commented pointer for `repeat:` and the
function list. cf. CR-12 (same staleness inside a docstring).

### DX-3 (P2) — `inspect --json` reports an instance, not the authored contract
**Did:** Ran `template inspect --json` on my event card and asked "could an AI author correct
data from this alone?"
**Happened:** `nodes` is the tree **compiled against preview_data**: my `chip-2` and `footer`
nodes are simply absent (preview_data has two tags and no rsvp_url), with no marker that
anything was conditional or repeated. An AI reading this concludes the template has exactly
two chips and no footer; supplying three tags then "creates" nodes that inspect never
disclosed. Nothing distinguishes structural (`repeat`/`if`) origins, and `functions` is a bare
name list — no signatures, arity, or one-line docs, so `format`/`locale_digits` usage still
requires reading source or guessing (spec §4.1.1 promises "an AI does not need to infer the
contract from raw source"). Distinct from CR-6 (broken-template ok=true) and CR-11 (default
null ambiguity).
**Must change:** report authored structure (list conditional/repeat nodes with their
condition/collection expressions, or add a `structural:` section) and give functions
signature + doc strings.

### DX-4 (P2) — undeclared-variable references are reported one at a time
**Did:** Added three nodes referencing three undeclared variables (`date_text`, `tags`,
`rsvp_url`), ran `template check`.
**Happened:** Only `date_text` reported; fixing it surfaced the next error; three
check/fix/check round-trips total. Declared-variable *type* errors do aggregate (verified in
the code review's matrix), but reference errors fail fast — RR-4's whack-a-mole is back for
the single most common authoring mistake.
**Must change:** collect all ARC-TPL-014 reference errors in one validate pass.

### DX-5 (P2) — locales.yaml values are accepted unvalidated
**Did:** Authored `locales: {fa: {direction: sideways, digits: klingon}}` and rendered.
**Happened:** Exit 0, no diagnostic. Top-level shape *is* checked (`locales: 42` →
ARC-TPL-098, good), but field values are not, so an author preparing locale files today gets
no feedback and the garbage surfaces only when Phase 2 starts applying locales. Related:
CR-2 (`--locale` flag missing entirely).
**Must change:** validate `direction`/`digits`/known keys per locale entry now, with located
errors.

### DX-6 (P2) — `explain` entries mostly restate the inline hint
**Did:** Ran `explain` on the six codes I actually hit (TPL-014, TPL-002, LAY-012, TPL-070,
TPL-071, TPL-097).
**Happened:** TPL-014 and TPL-002 add modest value (dual cause; "indentation, quoting, or a
stray character"). LAY-012, TPL-070, TPL-071, TPL-097 are word-for-word the inline hint with
a title — the command adds zero information at the moment an author escalates to it.
LAY-012's entry is the sharpest miss: the common real cause (an expression in a constraint —
exactly how I got there) is never mentioned. The unknown-code error ("may not be emitted by
this build") is good.
**Must change:** each entry should carry at least one sentence the one-liner cannot: the
typical *cause* and the boundary of the feature (explain is the right home for "constraints
are static in this phase"). The catalog-generated architecture (per code review) makes this
cheap.

### DX-7 (P3) — inspect reports formats only in canonical points
Authored `width: 1080px`; inspect returns `"width_pt": 810.0`. The one authoring-facing JSON
surface answers in an internal canonical unit the author never wrote — a soft IR leak
(§6.3 "no command requires knowledge of IR classes") and a real round-trip hazard for AI
authors patching sizes. Include the authored form (`"width": "1080px"`) alongside pt.

### DX-8 (P3) — scaffold README's edit loop doesn't match its render command
The README says "Edit `data.yaml` to change `title`/`subtitle`" but its render command passes
no `--data`, so it renders preview_data and edits to data.yaml do nothing to that command's
output. First-five-minutes confusion for exactly the audience the scaffold serves. Either
pass `--data` in the README's render line or say the no-data render uses `preview_data`.

### DX-9 (P3) — doctor never states where Arcavex will read/write
With `ARCAVEX_HOME` explicitly set, doctor reports the OS temp dir and nothing about
ARCAVEX_HOME, the preview cache location, or config provenance (§6.3 precedence chain). The
env var *is* honored (preview wrote under `$ARCAVEX_HOME/cache/preview/`, path byte-stable
across runs) — doctor just doesn't say so. Add an `arcavex_home`/`preview_cache` row with the
source of the value (env/default).

### DX-10 (P3) — message-polish batch
- Watch on a nonexistent file prints "render failed (kept last good preview)" when no preview
  exists yet — untrue on first failure.
- ARC-TPL-060's hint is always "Check the '{{ … }}' expression syntax" even when the message
  is already precise ("unknown function 'shout' (available: …)", "upper() takes exactly one
  argument") — the hint adds noise, not signal.
- ARC-TPL-014 for a *required-but-missing* variable during `template check` (no data file in
  play) hints "Add 'date_text:' to your data file"; in check's context the actionable fix is
  preview_data.
- A typo'd variable (`titel`) gets no "did you mean 'title'?" — the declared-name set is in
  hand, and this is the most common watch-loop error.
- Non-watch `preview` prints `changed=(initial)` — watch jargon in a one-shot command.
- After `template split`, the comment introducing `variables:` stays orphaned in
  template.yaml while its section moved to schema.yaml.

## §6.3 audit

| # | Contract line | Verdict | Evidence |
|---|---|---|---|
| 1 | `template new` generates a renderable example | PASS | Scaffold rendered out of the box, exit 0, no data needed |
| 2 | `preview --watch` starts the loop | PASS | One command; stable path printed each cycle |
| 3 | Saving any dependent file triggers one incremental rebuild | PASS* | template.yaml + data.yaml verified (~190 ms wall incl. debounce); out-of-tree assets not watched = CR-9; startup race = CR-7 |
| 4 | Errors keep previous preview + exact location + hint | PASS | YAML break at line, semantic error with node keypath; preview bytes intact; instant recovery |
| 5 | `layout inspect` explains geometry | N/A | Phase 2 by brief |
| AI-1 | Inspect schema/catalogs as JSON | PARTIAL | Variables/formats/functions/preview_data present; but instance-not-contract nodes (DX-3), pt-only formats (DX-7), bare function names, CR-6/CR-11 |
| AI-5 | Correct from structured diagnostics | PASS | `--json` diagnostics carry code/severity/message/file/keypath/line/hint |
| P-1 | One-file templates, direct render, sensible defaults | PASS | Whole session ran without project/config; split equally first-class (ambiguity diagnostic even cites formats.yaml) |
| P-2 | Projects/libraries/styles/extensions appear only when invoked | PASS | Never surfaced |
| P-3 | No command requires IR knowledge | PASS* | Only leak is inspect's pt-only canvas report (DX-7) |
| P-4 | No ordinary template requires Python | PASS | |
| P-5 | No manual CAS hash / asset registration | PASS | (assets lightly exercised this session) |
| P-6 | Infer unambiguous value + report it | PASS | `inferred: data=preview_data, format=s, output=coerce.s.png` |
| P-7 | Ambiguity → diagnostic, never a silent choice | PASS | ARC-TPL-021 lists both formats; located |
| P-8 | Inference only when exactly one valid choice | PASS | Two formats → refusal |
| P-9 | Config precedence CLI → ARCAVEX_* → … | PASS* | ARCAVEX_HOME honored for preview cache; full chain untested (no project.yaml/config.toml yet); doctor doesn't report provenance (DX-9) |
| P-10 | Default output name deterministic and shown **before** rendering | FAIL | CR-1: success path prints it before the confirmation but only after the facade renders; render-failure path never states it |
| D-1 | Every diagnostic code has a concise reference entry | PASS* | Coverage enforced by test; entry *depth* uneven (DX-6) |

## Friction log (verbatim moments)

1. `template new` into a non-empty dir → clean ARC-TPL-070 with hint. Fine.
2. Scaffold render: subtitle default "Edit data.yaml to change me" + README render command
   that ignores data.yaml → edited data.yaml, saw no change (DX-8).
3. Wrote the natural `repeat:` tag row → ARC-LAY-012 with a hint about offset spelling when
   my actual mistake was "expressions don't work here" (DX-1).
4. Removed the expression → silent triple-overlap render, exit 0 (DX-1).
5. Three undeclared variables → three separate check/fix cycles (DX-4).
6. `check`'s hint told me to fix a data file that wasn't part of the command (DX-10).
7. Watch session: break-YAML → located error, preview kept; typo `titel` → located error
   naming node and keypath but no did-you-mean; fix → 80 ms recovery. Best part of the phase.
8. `split` mid-session: worked, comments kept, still rendered byte-stably; the orphaned
   section comment was the only wrinkle; duplicate-section ARC-TPL-097 names both files.
9. `explain ARC-LAY-012` after hitting it → learned nothing new (DX-6).
10. `doctor` with fresh ARCAVEX_HOME → all ok, but never says where home/cache is (DX-9).

## What impressed

- **The loop is fast enough to feel instant.** 190 ms save-to-preview wall time (18-35 ms
  compile, 60-140 ms render) against a 2 s budget; the atomic-write + stable-path design means
  an image viewer just sits on one file and live-updates.
- **Watch is resilient beyond spec.** Pointed at a *nonexistent* file it starts, reports the
  miss, and the moment the file appears it renders it — no restart. Seeded errors never cost
  the last good preview.
- **Diagnostic craft is genuinely high.** ARC-TPL-058 names the duplicate key value *and* the
  two item indices; ARC-TPL-060 lists all nine available functions; ARC-TPL-021 points at
  `formats.yaml` (the right sidecar!) in a split template; ARC-TPL-016 lists valid types;
  RR-2's ARC-TPL-018 warning ("Quote the value in your data") is exactly right.
- **First-run output is designer-grade.** The scaffold's dark card with the mint accent bar
  is something an engineer would show a designer without apologizing; the evolved event card
  (`outputs-tmp/dx1/event-card.png`) — Persian digits via `locale_digits` + Vazirmatn, pill
  chips, conditional RSVP footer — looks like a real product screenshot, all from YAML in one
  session.

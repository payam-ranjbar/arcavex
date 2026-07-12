# Phase 00 — DX & Design Review

Reviewer: Fable DX agent. Method: followed README as a brand-new developer, rendered
hello-poster, authored a fresh template from scratch using only README + example as teaching
material, then seeded 15+ deliberate mistakes and judged every diagnostic (location, hint,
exit code, JSON shape). All commands run with `.venv\Scripts\arcavex.exe` from repo root.
Scratch artifacts under `outputs-tmp/dx/`.

## Verdict: REMEDIATE

The happy path is genuinely good — README quick start works verbatim, repeated renders are
byte-identical, an unaided newcomer can author a working template on the first try, and most
diagnostics are located, hinted, and correctly exit-coded. But Phase 0's own exit criterion —
"failing inputs produce located diagnostics and correct exit codes" — fails on five inputs,
three of them *silent successes* (wrong or missing output with exit 0) and two internal-error
leaks (exit 5 for ordinary author mistakes). Those must be fixed before this phase closes.

## What works (verified, keep)

- README quick start command runs exactly as written; exit 0; output announced.
- Byte determinism: two renders of hello-poster produced identical sha256
  (`8548a557…`), `cmp` identical.
- `--json` diagnostic objects match §3.6 field-for-field (code/severity/message/
  source{file,keypath,line}/hint). JSON goes to stdout, human output to stderr, `--quiet`
  suppresses human output but preserves exit codes. Machine-usable today.
- Exit codes 1 (validation), 2 (usage), 3 (missing template/data file), 5 (internal) observed
  correctly for the cases that raise at all.
- Excellent diagnostics: unknown format lists available formats; unknown node type lists valid
  types with file+line+keypath+node id; over-constrained axis names the node, axis, and both
  anchors; `repeat:` → ARC-TPL-050 "not supported in this build … arrive in Phase 1"; `.jpg`
  output → ARC-EXP-011 "Phase 0 exports PNG only". These are the house standard — the findings
  below should be brought up to it.
- Authoring model: predictable, minimal YAML; guessing `shape: circle`, `upper()`, arithmetic
  in interpolation, and bottom/right anchors from the example alone all worked first try. No
  IR classes, kernel names, or engine internals leak into template syntax or diagnostics.

## Findings

### DX-1 (P0) Missing required variable silently renders wrong output — root cause identified

**Did:** removed `name` (required) from data; ran render and validate.
**Happened:** render exit 0 and produced a poster with the *preview_data* value baked in;
`validate --json` returned `{"ok": true}`. Root cause: `preview_data` is merged underneath
`--data` as a fallback, so the required check never sees a gap. Proof: with `preview_data`
stripped from the template, the correct ARC-TPL-014 error fires.
**Must change:** `--data` values must not be backfilled per-key from `preview_data`.
preview_data should apply only when `--data` is omitted entirely (and that fallback must be
announced — see DX-7). Required-variable check runs against the user's data. This is the
brief's own named deliverable (item 7) and §4.1.2 "missing variables are errors"; silently
rendering placeholder content into a user's asset is the single worst failure mode for both
personas.

### DX-2 (P1) Under-constrained node silently vanishes

**Did:** removed the `size:` spec from a text node (leaving anchors only).
**Happened:** exit 0; the node simply did not render — title text gone from the PNG, no
diagnostic anywhere. Brief item 8: "each node must resolve exactly one x, one y, w, h;
under/over-constrained -> ARC-LAY error with node id". Over-constrained produces an exemplary
ARC-LAY-031; under-constrained produces nothing.
**Must change:** under-constrained axis → located ARC-LAY error naming the node and the
missing constraint, exit 1.

### DX-3 (P1) Bare-number canvas dimension crashes the engine

**Did:** `canvas: {width: 800, height: 400px, dpi: 96}` (brief item 2: bare numbers = px).
**Happened:** ARC-INT-999, exit 5, hint leaks `TypeError: pybind11::init(): factory function
returned nullptr`. Bare numbers in *node* `size:` work fine, so parsing is inconsistent:
canvas width/height as YAML ints reach skia unconverted.
**Must change:** canvas dims go through the same Dim parser as node dims (bare = px), or —
if canvas is deliberately stricter — a located ARC-IR-011. A pybind nullptr is never an
acceptable answer to a one-character template edit.

### DX-4 (P1) Nonexistent asset path → internal error, wrong exit code, path leak

**Did:** pointed an image node at `../reference/NOPE.png`.
**Happened:** ARC-INT-999, exit 5, hint embeds the raw
`ValueError: File not found: C:\Users\payam\…\NOPE.png` (absolute path). Should be a located
ARC-AST diagnostic at the node's keypath with exit 3 (§6.1.3: missing asset). The facade's
wrap-as-INT-999 safety net works, but this is a routine authoring mistake, not an unexpected
condition.
**Must change:** first-class ARC-AST error, file+keypath of the `asset:` field, template-relative
path in the message, exit 3.

### DX-5 (P1) Unknown font family silently falls back

**Did:** `font: ComicNeueSans` (not in library-seed).
**Happened:** render exit 0 with a fallback typeface visually identical to Inter; `validate`
says "OK template is valid". §6.1.3 reserves exit 3 for missing fonts; nothing in human or
JSON output even mentions the substitution. An author can ship a whole campaign believing
their brand font was used.
**Must change:** unknown family → error (exit 3) or at minimum a warning diagnostic naming the
requested family, the substitute, and the available families; validate must report it too.

### DX-6 (P1) No default output name when `-o` omitted

**Did:** ran render without `-o`.
**Happened:** ARC-EXP-010 "No output path was provided", exit 1. §6.3: "Default output naming
is deterministic and shown before rendering: `<template>.<format>[.<locale>].<ext>`." Scope
caveat: the brief's CLI signature shows `-o OUT`, so implementers may have read the default as
out of scope — but §6.3 is a release criterion and the lead scoped this review to it. Cheap to
add now (`hello-poster.square.png`, announced before render) and it removes the only broken
step in the newcomer flow I hit.

### DX-7 (P1) Inferences and fallbacks are silent

**Did:** rendered a one-format template without `--format` (correctly inferred, good);
rendered without `--data` (preview_data used).
**Happened:** neither the human line nor the `--json` object mentions the inferred format or
the preview_data fallback. §6.3: "A command that can infer an unambiguous value should do so
and report the inference in verbose/JSON output."
**Must change:** add e.g. `"inferred": {"format": "card", "data": "preview_data"}` to the JSON
response and a one-line note in human output. (Ambiguous format correctly errors with the
available list — ARC-TPL-021 is fine as-is.)

### DX-8 (P2) ARC-TPL-014 cites the wrong file/line pairing

**Did:** missing required var with no preview_data fallback.
**Happened:** `(data-missing-required.yaml, line 4, at name)` — but that data file has one
line; line 4 is the variable *declaration* line in the template. File from one source, line
from another. An AI following §6.3's "correct from structured diagnostics" would patch line 4
of a 1-line file.
**Must change:** either point at the template declaration (file+line consistent) or at the
data file with no line; never mix.

### DX-9 (P2) ARC-IR diagnostics missing line numbers

**Did:** invalid unit (`40cm`, `24vw`) and invalid color (`#zzz`).
**Happened:** ARC-IR-011 / ARC-IR-030 carry keypath but `line` is absent, while ARC-TPL
diagnostics carry both. The ruamel line info exists at load time; it's being dropped on the
path into IR validation. Keypath alone is workable for AI, weak for humans in a long file.

### DX-10 (P2) `--json` response models are unversioned

**Happened:** `{"ok", "output_path", "content_sha256", "diagnostics"}` — no version/schema
field. §6.1.3: "Machine-readable output uses versioned response models." Adding a field later
is easy; consumers keying on shape without a version marker is the thing the spec is trying to
prevent. Add `"response_version": 1` (or similar) now, before MCP (Phase 1+) freezes the shape.

### DX-11 (P2) README teaches one command and nothing else

**Did:** step 3 of this review — authored from scratch using only README + example.
**Happened:** it worked, but purely by cargo-culting the example. Nothing documents: available
node types (`circle` is discoverable only via the unknown-type error message), the anchor
mini-syntax and its no-spaces rule, unit rules (bare = px), preview_data semantics, `| default`,
`\{{` escape, available functions, or that `--data` can be omitted. Full reference docs are a
later-phase deliverable, but a 40-line "template anatomy" section in the README (or
`docs/authoring.md`) is Phase-0-cheap and removes the guesswork I hit.

### DX-12 (P3) Anchor offset mini-language is whitespace-brittle and unit-inconsistent in hints

**Did:** wrote `left: parent.left + 40px` (spaces).
**Happened:** ARC-LAY-012 "invalid offset '+ 40px'", hint "Offsets look like '+20pt' or
'-6mm'". Good diagnostic — but `{{ }}` expressions tolerate spaces and this second
mini-language does not, and the hint shows pt/mm while every shipped example uses px. Either
accept whitespace or keep the hint exactly matching example idiom.

### DX-13 (P3) hello-poster as a teaching artifact: three polish items

Rendered output is legible with clear hierarchy (title/subtitle/accent card read correctly).
But: (a) `logo.png` is fully opaque (alpha channel present, min alpha 255) so it renders as a
white sticker-box on the dark poster — the one visually wrong element; (b) the asset path
`../reference/logo.png` escapes the template directory, so copying `hello-poster/` breaks it —
§6.3 calls examples "copyable"; (c) the example demonstrates no expression beyond bare
interpolation (`| default`, arithmetic, functions all unshown). Fix (a)+(b) by placing a
transparent logo inside `hello-poster/`.

### DX-14 (P3) Malformed-YAML diagnostic is noisy

ARC-TPL-002 embeds the raw ruamel message including `in "<unicode string>"` and duplicated
location text, with a generic hint. Located and correct exit code, just below the house
standard set by ARC-TPL-031. Reformat to one location + one caret excerpt.

### DX-15 (P3) `hstack` rejected as generic unknown type

Brief item 8 asks stacks to be rejected with a clear "not supported yet". ARC-TPL-031 lists
valid types (good) but, unlike the exemplary ARC-TPL-050 for `repeat:`, gives no signal that
stacks are a planned Phase 2 feature rather than a typo.

## Later-phase notes (not defects now)

- `template new/inspect/split`, `preview --watch`, `layout inspect`, `explain`, `doctor`, MCP:
  Phase 1+ per spec; correctly absent. Nothing in the current YAML shape or JSON output would
  block them — *except* DX-10 (unversioned JSON) which gets harder to retrofit once MCP mirrors
  these models, and DX-12's whitespace-sensitive anchor grammar, which `layout inspect` will
  have to explain later; settling its tolerance now is cheaper.
- Structural `if:`/`repeat:` correctly rejected, not faked. Verified.

## Bottom line

Accept the architecture and the diagnostic *format* — they are exactly what §3.6 promises.
Remediate the five silent/crash paths (DX-1..DX-5) and the two §6.3 reporting gaps (DX-6,
DX-7) before closing Phase 0; the rest can ride along or be ticketed.

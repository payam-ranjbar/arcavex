# Phase 00 re-review (fresh, post-remediation)

Reviewer: Fable (independent re-review agent), 2026-07-12.
Method: no prior context; read brief, both reviews, remediation report, spec §3.6 / §4.1.2 /
§6.1.3 / §6.3; re-ran every gate myself; reproduced every original P0/P1 failing scenario with
fresh scratch templates (under the session scratchpad, not `outputs-tmp/`); read the remediated
compiler, solver, backend, CLI, and facade; inspected the rendered PNG visually. No production
code or tests were touched.

## Verdict: ACCEPTED

All four P1s from the code review, the P0 and all five P1s from the DX review are verifiably
fixed — each reproduced from its original failing input and observed producing the required
located diagnostic and exit code. Gates are clean. The render is visually correct and
byte-deterministic. Remaining findings are P3 polish; none is required Phase 0 behavior.

## Gates (run by me)

| Command | Result |
|---|---|
| `pytest tests -q` | **97 passed**, exit 0 |
| `ruff check src tests` | clean |
| `mypy src/arcavex/kernel --strict` | clean (12 files) |
| `lint-imports` | 2 contracts KEPT ("Kernel is pure", "Built-ins do not import clients or the composition root"), 0 broken |

## Original failing scenarios, reproduced

Every probe used a fresh scratch template; codes/exits observed directly.

| Original finding | Probe | Observed |
|---|---|---|
| CR-1/DX-1 (P0) preview_data masks missing required var | hello-poster + data file missing `title` | `validate` and `render` both exit **1**, `ARC-TPL-014` located at `template.yaml` **line 4** (the declaration line — file and line from the same source), no PNG written |
| CR-2 (P1) `visible: false` renders | full-canvas red rect `visible: false` over blue bg | exit 0; center pixel `(0, 0, 255, 255)` — hidden node not painted |
| CR-3/DX-4 (P1) missing asset → exit 5 | image node → `does-not-exist.png` | `render` exit **3**, `ARC-AST-001` at `root.children[0].asset` + line 11, template-relative path in message; `validate` also exits 3 (compile-time check) |
| CR-4 (P1) non-goal sections silent | separate `locales:`, `styles:`, format `patch:` templates | `ARC-TPL-092` (line 2), `ARC-TPL-093` (line 4), `ARC-TPL-095` (`formats.card.patch`, line 5) — each located, "not supported in this build", exit 1 |
| DX-2 (P1) under-constrained node vanishes | text node with anchor but no `size:` | exit **1**, `ARC-LAY-032` naming the node, keypath `…constraints.size`, actionable hint |
| DX-3 (P1) bare canvas number crashes | `width: 800` (bare) + `dpi: notanumber` | bare width renders exit 0; bad dpi → `ARC-IR-014` located at `formats.card.canvas.dpi` line 4, exit 1 — no pybind leak |
| DX-5 (P1) unknown font silent fallback | `font: ComicNeueSans` | exit **3**, `ARC-RND-010` located at the `style.font` line, hint lists available families (Estedad, Inter, Lalezar, Vazirmatn) |
| DX-6 (P1) no default output name | `render single.yaml` (no `-o/-f/-d`) | exit 0, writes `single.card.png` (`<template>.<format>.png` per §6.3), announced |
| DX-7 (P1) inferences silent | same probe | JSON `"inferred": {"data": "preview_data", "format": "card", "output": "single.card.png"}`; human output prints `inferred: data=preview_data, format=card, output=single.card.png` **before** the `Rendered` line |
| CR-5 (P2) budget → exit 1 | 5000-term expression | exit **4**, `ARC-TPL-062`, located |
| CR-9 (P2) line_height ignored | `line_height: 1.5` | exit 1, `ARC-TPL-053` located, "not supported in this build" |
| DX-15 (P3) hstack generic error | `type: hstack` | `ARC-TPL-052` "Stacks arrive in Phase 2", located |

## Render and determinism

- `render examples/hello-poster … --format square` → exit 0. Inspected the PNG: dark navy
  background, pink rounded accent card, white "Hello, Arcavex" title and legible subtitle,
  logo top-left rendered **transparently** on the dark background (no white sticker box).
- Two consecutive renders: identical SHA-256 (`91F91C93…`).

## Six flagged scrutiny areas

1. **CR-9 StrutStyle claim — verified true.** `python -c` introspection on skia-python
   144.0.post2: `StrutStyle` exposes only `setLeading`/`setStrutEnabled`; `TextStyle` has no
   height/strut methods. A faithful line-height multiplier is not expressible; rejecting per
   §4.3 is the correct call.
2. **DX-2 asymmetry — acceptable.** No `constraints` key → documented fill/top-left convenience
   (`compiler.py:678-689`, used by root/backgrounds); a present-but-incomplete block is a hard
   `ARC-LAY-032`; `size` without `anchor` still errors via the solver's `ARC-LAY-030`. No path
   silently vanishes a node.
3. **Variable type enforcement — low false-positive risk, one sharp edge.** `number` accepts
   int and float; bool kept distinct both directions; `color`/`image` are strings. The sharp
   edge: `year: 2026` against a declared `string` is now a hard error (probe confirmed,
   located + hinted). Strict but consistent with "diagnostics over silent correction" — watch
   for authoring friction (see RR-2). Also: a typo'd declared type (`type: strnig`) silently
   skips checking (see RR-1).
4. **validate not surfacing `inferred` — acceptable.** Spec §3.7 fixes
   `validate_template -> [Diagnostic]`; both §6.3 inference examples are render-side. Deliberate
   scoping, no spec violation.
5. **`Compiler(available_fonts=None)` — safe.** The only production constructor is
   `bootstrap.py:45`, which always passes `frozenset(text_service.families)`. `None` occurs
   only in unit tests.
6. **Reference assets untouched — verified.** `git status` shows `examples/reference/` neither
   modified nor untracked (tracked, clean); `examples/hello-poster/logo.png` is a new file.
   Pixel check: reference logo alpha extrema (255, 255) — the fully-opaque original;
   example logo (0, 255) — real transparency in the derived copy.

## Spot-checks for remediation-introduced defects

- **Solver** (`layout_anchors/solver.py`): `measure` threaded through the call stack — no
  mutable per-solve state remains; `visible` copied onto `LayoutNode` (layout stays honest,
  paint skips); `_parent_edge` raises `ARC-LAY-014` on unknown edges. No new defects.
- **Backend** (`backend_skia/backend.py`): `_visible()` gates at the top of `_draw_node`, so an
  invisible group correctly hides its whole subtree; image decode guarded (exception *and*
  None paths → `ARC-AST-002`). No new defects.
- **CLI/facade** (`cli.py`, `kernel/api.py`): exit-code precedence INT > BUDGET > MISSING >
  VALIDATION is sound; `_build_facade_or_exit` wraps engine init (CR-8) with the icudtl hint —
  code-verified, not simulable without breaking ICU; UTF-8 forced for `--json`;
  `response_version: 1` present on both commands; default-output naming lives in the facade so
  the Python API gets it too; multi-format validate aggregates + dedupes. No new defects.

## Deferral judgments

| Item | Judgment |
|---|---|
| CR-12 group partial opacity | **Legitimate.** Not named Phase 0 behavior; `opacity: 0` correctly hides the subtree; partial group alpha needs `saveLayer` and has no Phase 0 consumer. Latent inconsistency, correctly flagged for Phase 1+. |
| CR-13 canonical float repr | **Legitimate, but must not slip past hash persistence.** The brief does name `repr(round(x, 6))`, so this is a spec-letter deviation in a Phase 0 deliverable — however `canonical_hash` has no production caller, the current behavior is deterministic, and re-deciding numeric canonicalization (int vs float) belongs with the first real consumer. Ticket it as a hard precondition for whichever phase persists a hash. |
| CR-14 traversal guard / absolute asset_path | **Legitimate.** Brief explicitly allows direct template-relative resolution in Phase 0 ("full CAS lands later"); the shipped example no longer escapes its directory. |
| CR-15 evaluator bypasses TemplateFunction registry | **Legitimate, borderline.** The brief's required functions (`len`/`upper`/`lower`/`format`) all work; §4.1.2 registry-called functions (e.g. `locale_digits`) are Phase 1 features. The two parallel implementations are a real drift hazard — acceptable only because Phase 1 must wire the registry anyway. |
| bleed unused (CR-21 part) | **Legitimate.** Parsed and carried; nothing in Phase 0 (PNG, no print/PDF) consumes bleed. Insets-shape conversion is cosmetic without a consumer. |

## Remaining findings (none blocking)

| ID | Sev | Finding |
|---|---|---|
| RR-1 | P3 | A typo'd variable `type:` declaration (`type: strnig`) is silently accepted — `_check_variable_type` (`compiler.py:273-275`) returns when the declared type is unknown. CR-21's "typos accepted" is only half-fixed: values are now enforced for *known* types, but an unknown type name draws no diagnostic and disables checking for that variable. One-line fix: unknown declared type → located ARC-TPL error listing valid types. |
| RR-2 | P3 | ARC-TPL-015 strictness: `year: 2026` against `type: string` is a hard error rather than a coercion or warning. Defensible (and located + hinted), but this is the most likely authoring friction point of the new enforcement; consider documenting or softening for numeric→string specifically. |
| RR-3 | P3 | `ARC-AST-002` (undecodable image, render-time) carries no source location — the backend has no keypath/file. Below the house standard the compile-time `ARC-AST-001` now sets; threading the node's source into `ResolvedImage` (or pre-validating decodability at compile time) would fix it. Solver-raised diagnostics (ARC-LAY-014/020/030/031) similarly locate by node id only — accepted in the original review, unchanged. |
| RR-4 | P3 | Fail-fast section rejection: a template with `locales:` + `styles:` + format `patch:` reports only the first offense per run (three runs to see all three). Consistent with the codebase's raise-on-first style; aggregating the §-092..096 checks would be friendlier to the AI correction loop. |
| RR-5 | P3 | §6.3 says the default output name is "shown before rendering"; the CLI prints `inferred:` (including the output name) after the render call returns. Cosmetically indistinguishable on success; on a render failure the name isn't announced. Not worth churn now; note for the watch-mode phase. |

## Exit criteria check (brief)

- Hello poster renders from a one-file template, no project/config — **yes** (visually inspected).
- PNG visually correct — **yes** (text visible, positioned, colored background, transparent logo).
- Repeated render byte-identical — **yes** (matching SHA-256).
- Failing inputs → located diagnostics + correct exit codes — **yes** (12 scenarios probed:
  exits 1/3/4 and located codes in every case; exit 5 reserved for genuine internals).
- Tests pass — **yes** (97).

Phase 0 is accepted. RR-1..RR-5 can ride along as Phase 1 tickets.

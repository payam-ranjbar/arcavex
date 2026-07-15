# Phase 03 — DX & design review (effects, styles, shapes)

Reviewer: Sonnet 5, DX/design lane. Scope: commit `0d051d7`. Read only `README.md` and
`examples/pop-art-grid/` before authoring (per brief); consulted source/spec for the
diagnostics/DX audit tasks that require precision. All renders under `outputs-tmp/dx3/`.

## Verdict: **remediate**

The engine underneath is in good shape — deterministic, fast (1.7s vs the 8s pop-art-grid
budget), and the diagnostics for unknown effects/presets/roles/generators are genuinely
excellent (located, alternatives listed, correct exit codes). But three release-criterion-level
DX gaps (§6.3 is explicit that these are release criteria, not aspirations) and one flagship
visual-quality problem should be fixed before sign-off: a documented `--style` CLI flag that
does not exist, two new JSON commands missing the versioned-response envelope every other
command has, and a golden/showcase example whose halftone treatment reads muddier than the
effect is actually capable of.

## Findings

### DX-1 (P1) — pop-art-grid's flagship visual undersells the halftone effect

**Did:** rendered `examples/pop-art-grid/template.yaml` (the exact acceptance command) and
viewed all four cells at full resolution. Also rendered the isolated golden
`tests/golden/goldens/win-x86_64/effect-halftone.png` (halftone alone, on a radial-gradient
fixture) and my own from-scratch halftone panel (`outputs-tmp/dx3/my-poster/out2.png`).

**Happened:** the isolated halftone golden shows real, convincing tonal modulation — dot size
and density genuinely track luminance, fading to near-white at the brightest point. But in
pop-art-grid, each cell's chain is `grade → duotone → posterize(levels:5) → halftone → grain`;
posterize collapses the source portrait to flat bands *before* halftone sees it, so three of
four cells read as a diffuse dot-covered blob rather than a recognizable comic-book portrait.
The bottom-left cell (palette `warhol_3`: yellow fill `#FFEB3B`, ink `#212121`) has the weakest
internal contrast of the four and is the hardest to read — dark-on-dark dot texture with no
clear silhouette. Only the bottom-right cell (`warhol_4`, orange/near-black) reads clearly as a
face-and-shoulders shape. This is the project's acceptance artifact for the whole effects
system (spec §11 Phase 3, golden case #3) — it should be the strongest advertisement for
halftone, not the muddiest.

**Must change:** either drop or reduce `posterize` in the per-cell chain (halftone already does
its own quantization via dot coverage; stacking a 5-level posterize in front of it is largely
redundant and actively destroys the gradation halftone needs), and swap `warhol_3`'s ink/fill
pairing for higher contrast. Re-render and re-eyeball before calling this golden case done.

### DX-2 (P1) — `--style` is documented but does not exist on any command

**Did:** README states plainly: *"`--style` on the CLI overrides the template's opt-in."*
Ran `arcavex render --help`, `arcavex validate --help`, `arcavex preview --help`.

**Happened:** none of the three commands expose a `--style` option — only `--data`, `--format`,
`--locale`, `--output`/`--dpi`/`--debug` (render/preview) or nothing extra (validate). An
author following the README to preview a template under a different style pack has no way to
do it without editing the template's `style:` line.

**Must change:** implement the flag (it's exactly the kind of CLI-flag-wins-over-template-value
precedence pattern already established for locale/format), or remove the claim from the README
until it exists. As written it's a broken promise on day one of Phase 3.

### DX-3 (P1) — `style list`/`style inspect --json` skip the versioned-response envelope

**Did:** compared top-level JSON keys across commands:
```
validate --json        -> response_version, ok, diagnostics
explain --json          -> response_version, code, found, title, summary, fix, message
template inspect --json -> response_version, ok, ... (+ more)
style list --json       -> ok, styles, diagnostics            (no response_version)
style inspect --json    -> ok, style, diagnostics             (no response_version)
```

**Happened:** every pre-existing command's JSON is a versioned response model; the two new
Phase-3 commands are not. §6.3 / §6.1.3: *"Machine-readable output uses versioned response
models rather than parsing human console text."* An MCP client or AI author has no way to detect
a future breaking change to `style list`/`style inspect`'s JSON shape.

**Must change:** add `response_version` to both response models, consistent with the rest of
the CLI.

### DX-4 (P2) — effect length params silently reject `px`, unlike everything else in the template

**Did:** authored a `drop-shadow` on a headline guided only by the README, guessing
`{dx: 6px, dy: 6px, blur: 12px, ...}` — the same unit convention README uses everywhere else
("Bare numbers are pixels; `px`, `pt`, `mm`, and `%` are also accepted").

**Happened:** `ARC-FX-902 ... Value error, effect lengths must be pt or mm, not 'px'`. Effect
geometry params use a different, narrower unit grammar than layout constraints/sizes, and
nothing in the README's effects paragraph says so.

**Must change:** either accept `px` for consistency with the rest of the authoring surface, or
add one sentence to the README's effects section calling out the pt/mm-only rule before an
author hits it as a guess-and-check error.

### DX-5 (P2) — invalid-param errors report only the first offending field

**Did:** deliberately set two invalid `starburst` params at once (`points: 2, inner_ratio: 1.4`,
both out of range).

**Happened:** `ARC-FX-912 ... points: Input should be greater than or equal to 3` — no mention
of `inner_ratio` at all; fixing `points` and re-running is what surfaces the second error.
`arcavex explain ARC-FX-902/912` confirms this is intentional ("the message names the first
offending field"), not a bug, but it costs an extra render-and-fail round trip per additional
mistake, and pydantic already collects every field error for free.

**Must change (nice-to-have, not blocking):** list all invalid fields in one diagnostic.

### DX-6 (P2) — no catalog/schema discovery command for effects

**Did:** tried to author a `drop-shadow` knowing only the README's bare name list ("blur,
drop-shadow, glow, duotone, threshold, grade, posterize, palette-map, grain, noise, ink-bleed,
halftone, channel-offset, torn-paper, and edge-wear" — no params for any of them). Guessed
`opacity` as a param name (reasonable CSS-box-shadow instinct); it doesn't exist
(`ARC-FX-902 ... opacity: Extra inputs are not permitted`).

**Happened:** the only way to learn an effect's real param names is to trigger an error (which,
per DX-5, only reveals one field per attempt) or read `effects_core/` source. Compare this to
`arcavex template inspect --json`, which explicitly lists every template function's signature
"so an AI author need not read source" — `style list`/`style inspect` similarly expose full
preset/role param dictionaries. Effects have no equivalent discovery surface.

**Must change:** even a lightweight `arcavex explain` extension or a `--list-effects`
flag surfacing each effect's pydantic schema would remove most of the guesswork; this is the
single biggest source of friction in authoring from the README alone.

### DX-7 (P3) — `ARC-STY-001` is missing the location suffix its siblings have

**Did:** compared `ARC-STY-001` (unknown style pack) against `ARC-STY-010`/`ARC-STY-011`
(unknown preset/role) and `ARC-FX-910/911/912` (unknown effect/geometry-mismatch/bad shape
params) — all triggered from the same template.

**Happened:** every other one of these diagnostics ends with
`(path\template.yaml, at root.children[...])` or a line number; `ARC-STY-001` does not, even
though the offending `style: pop-artt@0.1` line is right at the top of the same file.

**Must change:** add the same `(file, at style)` suffix for consistency — minor, but this
family of errors is otherwise a genuine DX highlight and this is the one gap in it.

### DX-8 (P3) — no guidance on text legibility over textured effect panels

**Did:** placed a headline directly over a `halftone` panel (testing task-4's "legibility over
textured backgrounds" question) — first attempt used the role's default dark text color and was
nearly unreadable against the black/white dot mesh; fixing it required manually choosing a light
fill plus a dark drop-shadow.

**Happened:** this worked once I thought about it as a designer, but nothing in the docs warns
that text-over-raster-effect is a legibility trap, and the framework offers no assist (no
auto-contrast, no recommended pairing). Given style packs are explicitly meant to combine
halftone/grain/noise panels with role-based headings, this combination will recur.

**Must change (optional, doc-only):** one README note recommending a solid plate or high-contrast
color/shadow pairing when text sits over a textured panel — see pop-art-grid's own title, which
deliberately avoids this by putting the headline on a flat yellow bar rather than the halftone.

## Visual-quality assessment

**pop-art-grid** (`outputs-tmp/dx3/popart.png`, byte-identical across two independent renders —
determinism holds): strong palette and layout instincts (four saturated Warhol quadrants, bold
yellow title bar, clean 2×2 grid), but per DX-1 the halftone treatment reads as noisy dot
texture with a vague blob rather than a comic-book portrait in 3 of 4 cells. As currently tuned
I would not put this in a README as the flagship effects showcase without first fixing the
posterize-before-halftone ordering and the low-contrast yellow/black cell. It's close — the
underlying shader is good (see the isolated halftone golden below) — but the composition doesn't
show it off.

**My from-scratch poster** (`outputs-tmp/dx3/my-poster/out2.png`, "NEON REVIVAL"): after fixing
my own layout mistake (first draft had the halftone panel and portrait image overlapping,
`outputs-tmp/dx3/my-poster/out.png`), this came out clean and presentable — cream text with a
dark drop-shadow reads clearly over the dot texture, the teal duotone+grade portrait shows
genuine smooth tonal gradation (no posterize in this chain, which is why it looks better than
pop-art-grid's portraits), and the pink accent-role subtitle pops against the paper background.
This is a positive data point: the effect/style primitives themselves are good, once composed
without the posterize-before-halftone trap.

**Per-effect swatches** (`tests/golden/goldens/win-x86_64/effect-*.png`, viewed all 14 plus
`fused-color-chain.png` and `halftone-sksl.png`):

| Effect | Verdict |
|---|---|
| blur | genuine soft blur, correct |
| drop-shadow | clean soft shadow, correctly offset and blurred, not clipped |
| glow | convincing cyan glow ring around the shape |
| duotone | smooth two-color gradient mapping, no banding |
| threshold | crisp concentric bands from the gradient fixture — clearly a hard cutoff, correct |
| grade | subtle, correct brightening/warming — arguably *too* subtle to read as its own effect in isolation, but that's expected of a grade |
| posterize | clean flat color bands, correct |
| palette-map | quantizes to distinct palette colors nicely — this one alone already looks pop-art |
| grain | fine monochrome-leaning texture, reads as film grain, correct |
| noise | colorful per-pixel RGB noise, visibly distinct from grain (a reasonable differentiation) |
| ink-bleed | **flag** — visually indistinguishable from a plain clean rounded rect at this scale; if it's supposed to show blotchy/organic ink bleed at the edges, it isn't visible in the golden and reads as a no-op |
| halftone | genuine dot-screen with real tonal modulation, best-looking effect in the set |
| channel-offset | subtle RGB fringing at the left/right edges — correct chromatic-aberration read, but very subtle |
| torn-paper | excellent — a real jagged, irregular torn edge, immediately reads as its name |
| edge-wear | **flag** — same as ink-bleed: nearly indistinguishable from a clean edge at this scale, hard to confirm it's doing anything |
| fused-color-chain | multi-color-effect chain produces a plausible smooth composite, no banding artifacts that would indicate fusion is broken |
| halftone-sksl (flat-gray fixture) | uniform dot mesh, which is the *correct* output for a flat-luminance input — good corroboration that halftone's variation in the other golden is genuinely luminance-driven, not random |

**Bounds honesty:** built a probe (`outputs-tmp/dx3/bounds-test.yaml`) — a card with a
`drop-shadow` sized well past the card's own layout box, no manual padding anywhere in the
template. The shadow rendered fully unclipped, soft all the way to its blur radius. `paint_bounds`
expansion works exactly as promised in spec §4.4/§4.5 — this is a real strength, not just a
documentation claim.

## Friction log (authoring from README + pop-art-grid alone)

1. Guessed `dx/dy/blur` in `px` for `drop-shadow` (README's stated default unit convention) →
   rejected, pt/mm only (DX-4).
2. Guessed `opacity` as a drop-shadow param (natural CSS instinct) → rejected, not a real field,
   with only a generic "check name/type/range" hint, no field list (DX-6).
3. Tried the node-level `effect_preset: halftone` shorthand (mentioned once in README, unlike
   the `{preset: name}` list form pop-art-grid actually demonstrates) on a plain shape node — it
   worked first try, no friction. Positive: both documented preset syntaxes work.
4. Shape generators (`starburst`, `speech_bubble`, `qr_code`) worked first try from the single
   line of spec-brief syntax (`type: shape, generator: name, params: {...}`) — zero trial and
   error, all three rendered exactly as their names promise.
5. Discovering `palette.<name>[i]` and `style_role`/`effect_preset` syntax was easy and
   unambiguous from the README prose plus one glance at pop-art-grid's `template.yaml`.
6. First composition attempt overlapped the halftone panel and portrait image because nothing
   warns about self-inflicted layout overlap when two independently-anchored siblings are
   sized without checking against each other — this is normal poster-authoring risk, not an
   engine defect, but `arcavex layout inspect` earns its keep here (not exercised in depth this
   pass, but the tool exists and would have caught it immediately).

## What impressed

- Determinism: two independent renders of pop-art-grid are byte-identical (verified via
  sha256).
- Located, alternatives-listing diagnostics for unknown effect (`ARC-FX-910`), unknown style
  (`ARC-STY-001`), unknown preset (`ARC-STY-010`), unknown role (`ARC-STY-011`), and geometry
  effect on an unsupported node type (`ARC-FX-911`, correctly rejects `torn-paper` on `text`)
  are all genuinely good — this is the diagnostics bar the rest of the effects surface should
  be held to (see DX-6).
- `style list`/`style inspect --json` give an author everything they'd need: full palettes,
  font stacks, effect presets with resolved params, and role defaults, in one call.
- Performance: pop-art-grid rendered in 1.7s against an 8s budget.
- Bounds honesty is real, not just documented (see above).
- All 5 `explain` entries checked (`ARC-FX-902`, `ARC-FX-910`, `ARC-FX-912`, `ARC-STY-001`,
  `ARC-STY-010`) are substantive, accurate, and match observed CLI behavior exactly.

## Summary for the record

Accept-with-remediation. Fix DX-1 (re-tune pop-art-grid's per-cell chain/palette so the
flagship example actually shows off halftone), DX-2 (`--style` flag, implement or un-document),
and DX-3 (`response_version` on the two new JSON commands) before calling Phase 3 done; the P2/P3
items are real but not blocking. The underlying effect/style/shape machinery is solid —
determinism, bounds honesty, and diagnostics are all better than a typical v1 effects system —
the gaps are concentrated in example polish and a couple of DX-contract omissions on the newest
surface area.

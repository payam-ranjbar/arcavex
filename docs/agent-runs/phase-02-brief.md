# Phase 02 brief — Layout, text, and locales (spec §11 Phase 2)

## Scope

1. **Full anchor resolver** (§4.2, extends Phase 0 solver):
   - Logical directions: nodes use `start`/`end`; resolved through the enclosing group's
     `direction` (ltr default, rtl flips). Physical left/right remain valid.
   - **Named sibling anchors**: `anchor: {top: title.bottom+16pt, start: parent.start}` —
     position relative to a sibling node's resolved edge. Dependency order via topological
     sort of sibling references; cycles -> located ARC-LAY error naming the cycle
     (constraint-cycle diagnostic is a required seeded failure in the task contract).
   - Size modes: `fixed` (dim), `%`, `fill` (remaining space), `fit_content` (text/image
     intrinsic), `aspect` (`aspect: 3:4` — one axis derived from the other) with optional
     `min`/`max` clamps.
   - **Stacks**: group `layout: hstack|vstack` with `gap`, `padding`, main-axis alignment
     (start|center|end|space_between), cross-axis alignment (start|center|end|stretch).
     Stack children may not also declare position anchors (error); size modes still apply;
     `fill` children share remaining main-axis space equally. Wrapping only with explicit
     `wrap: true` (may defer wrap with a not-supported diagnostic if time-boxed — do not fake).
   - Rotation: explicit `origin` (default center), post-transform AABB contributes to
     inspection and paint bounds.
   - Geometry normalized to 1/1024 pt before hashing/rendering.
2. **Text stack completion** (§4.3):
   - Multi-run text: `runs: [{text, style_role?|style overrides}]` shaping in ONE paragraph
     (Latin-inside-Farsi via per-run families is handled by SkParagraph fallback; keep single
     paragraph). Simple `text:` remains sugar for one run.
   - `paragraph: {align: start|end|center, direction: rtl|ltr|auto}` — auto = first strong
     character; direction wired via BiDi isolates (ADR-0001) + align mapping. Group `direction`
     provides the default.
   - **Fit policies**: `fit: {policy: shrink_to_fit, min_size}`, `truncate` (ellipsis "…",
     with RTL-correct placement — SkParagraph handles ellipsis position when we truncate by
     measured prefix; implement via binary search on text length), `wrap` (default), and
     `overflow: clip|allow|error`. Max 8 measurement iterations; non-convergence -> located
     ARC-LAY diagnostic with measured values. `max_lines` supported via measured line count
     (Height / first-line height) — document approximation.
   - OverflowState on LayoutNode: none|clipped|truncated|shrunk|overflowing (+ measured px).
     `overflow: error` -> ARC-LAY error, exit 1 (required seeded failure: "text overflow
     configured as an error").
   - Letter spacing, weight, slant/italic (skia FontStyle), language tag, NFC normalization.
     Unsupported typography fields still fail validation.
   - Missing glyph detection: probe unicharToGlyph across resolved chain at measure time ->
     warning diagnostic listing code points + attempted chain.
3. **Formats & locale system** (§4.1.4):
   - `formats:` full form: named canvas + optional `patch:` list. Patch ops exactly
     `set`, `remove`, `insert_before`, `insert_after`; paths address `nodes.<id>.<field...>`
     by stable ID; unknown path -> located error; ops applied in file order; provenance of the
     introducing layer kept for `--resolved` inspection.
   - `locales:` named entries: `{direction: rtl|ltr, digits: fa|en|latn|arab, fonts:
     {role-or-family overrides}, data: <overlay mapping>, patch: [ops]}`.
     Locale DATA overlay merge semantics (§4.1.4): mappings merge recursively, scalars
     replace, lists replace whole, `!delete` tag removes, null is a value.
     `digits: fa` applies locale_digits automatically to interpolated numeric output
     (document: explicit locale_digits() also available).
   - Data files may have locale variants (`data/event.fa.yaml` overlay chosen via --locale
     when a data DIRECTORY or base file with sibling overlays is used — keep simple: CLI
     --locale L + --data base.yaml automatically applies base.<L>.yaml overlay if present,
     reported as inference).
   - Resolution order enforced + inspectable: template values -> format patch -> locale
     patch (style/project layers come later; leave hook points).
   - `arcavex template inspect --resolved --format F --locale L` reports final values with
     originating layer.
4. **Masks** (§3.2 MaskGenerator, §4.5): registry-resolved mask components; built-ins in
   `builtin/masks_core/`: `rounded_rect(radius)`, `circle`, `diamond_grid(cell, gutter, angle)`
   (the reference-poster treatment: grid of diamonds as clip path with gutters as gaps).
   `mask: {component: name, params: {...}}` on any visual node; clips node content (and
   children for groups). Invalid mask params -> located ARC-FX/ARC-IR error via param schema.
5. **Layout inspection + debug overlay** (§6.1.1, §6.2):
   - `arcavex layout inspect TEMPLATE --data D --format F [--locale L] [--json]`: per-node
     resolved bounds (pt and px), absolute transform, paint bounds, overflow state, anchor
     chain derivation ("title.top = parent.top + 120pt"), overlaps between siblings, free
     regions summary; warnings list. JSON versioned. (API: inspect_layout in kernel.api.)
   - `render --debug` / `preview --debug`: overlay node bounds (colored), ids, text baselines,
     safe-area canvas margin lines. Deterministic overlay drawing.
6. **IPEN bilingual golden case #2 seed** (§8.5): create `examples/ipen-bilingual/` — a
   SIMPLIFIED bilingual event-poster template (NOT the full reference reproduction yet; that
   is a later dedicated task): Farsi headline + English subtitle, RTL group layout, one image
   with diamond_grid mask, date/time with fa digits, en+fa locales, square + story + a4
   formats. Renders all 6 combinations in tests (layout snapshot + smoke pixel checks).
   This example doubles as the locale/format acceptance artifact.
7. **Tests**: layout JSON bounds snapshots (§8.5) under tests/layout_snapshots/ with a
   snapshot-update mechanism (env var or make target, documented); property tests for anchor
   math; fit-policy tests incl. convergence failure; BiDi/RTL paragraph tests (metrics-based:
   RTL paragraph places first glyph right of center etc. — pixel-light); patch-op tests incl.
   unknown path, op order, remove+insert; locale overlay merge semantics incl. !delete and
   null-is-value; digit mapping; mask golden-ish pixel tests (diamond_grid: sample gutter
   pixel = background, cell pixel = image); inspect-layout JSON golden; debug overlay smoke;
   CLI transcripts for new flags; determinism re-check.

## Carry-over

Any open P2/P3 from phase-01 re-review marked "fix in phase 2" (check
docs/agent-runs/phase-01-rereview.md).

## Non-goals

Effects/styles (Phase 3), projects/library (Phase 4), MCP (Phase 5), extensions (Phase 6),
JPEG/WebP/PDF (Phase 7), hyphenation, wrapping stacks if time-boxed out (explicit diagnostic).

## Constraints

- Never a second shaper; all measurement through the text service.
- CompiledDocument stays immutable through layout; LayoutDocument carries everything the
  renderer needs (renderer must not re-read template).
- Patches operate on the template AST before expression evaluation? NO — spec §4.1.5 order:
  resolve style -> format patch -> locale data+patch -> project patch -> THEN evaluate
  expressions. Patches address authored node IDs (pre-repeat-expansion).
- Diagnostics keep file+keypath+line; patch-introduced values cite the patch layer.
- ruff / mypy-strict-kernel / lint-imports / all existing tests stay green.

## Acceptance commands

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\arcavex.exe render examples/ipen-bilingual/template.yaml --data examples/ipen-bilingual/data.yaml --format square --locale fa -o outputs-tmp/ipen-fa-square.png
.venv\Scripts\arcavex.exe render examples/ipen-bilingual/template.yaml --data examples/ipen-bilingual/data.yaml --format story --locale en -o outputs-tmp/ipen-en-story.png
.venv\Scripts\arcavex.exe render examples/ipen-bilingual/template.yaml --data examples/ipen-bilingual/data.yaml --format a4 --locale fa -o outputs-tmp/ipen-fa-a4.png
.venv\Scripts\arcavex.exe layout inspect examples/ipen-bilingual/template.yaml --data examples/ipen-bilingual/data.yaml --format square --locale fa --json
.venv\Scripts\arcavex.exe render examples/ipen-bilingual/template.yaml --data examples/ipen-bilingual/data.yaml --format square --locale fa --debug -o outputs-tmp/ipen-debug.png
```

## Exit criteria (spec Phase 2)

IPEN bilingual example renders Farsi and English in square/story/A4 from ONE template with
correct RTL layout, shaped Farsi, fa digits, masked image; layout inspect explains geometry;
seeded failures for constraint cycle, text overflow error, invalid unit, unknown node
reference in anchors, missing font, missing asset all produce located diagnostics with
correct exit codes.

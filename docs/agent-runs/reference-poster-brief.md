# Reference-poster brief — faithful IPEN template (task §9–§10)

Reproduce the supplied IPEN poster as a REUSABLE bilingual Arcavex template rendered by the
REAL engine (never hand-composited in an image editor), across 5 aspect ratios × 2 locales,
then pass the visual design-review loop.

## The reference (examples/reference/reference-poster.png, 720×914 ≈ 4:5)

Composition, top→bottom:
1. **IPEN logo** top-left (examples/reference/logo.png — the SUPPLIED asset, use it, do not
   recreate) + org caption "Iranian Professional and Educational Network" (bold, black).
2. **Hero photo** upper-right ~60%: a lit communications tower + golden fireworks on night sky,
   masked into a **diamond-grid** lattice (the builtin `diamond_grid` mask — rotated square
   cells with white gutters). This is the signature treatment.
3. **Farsi display headline** "یک فنجان تجربه" (large, bold, black), left-of-hero.
4. **Farsi subtitle** two lines: "دورهمی و انتقال تجربه ایرانیان فعال در صنعت و آموزش".
5. **Date/time + label boxes**: red-outlined boxes. Label box "تاریخ رویداد" (Event date);
   pink-fill box "۱۵ جون / ۱۷:۰۰" (15 June / 17:00, Persian digits in fa).
6. **Venue box**: red-outlined "Hunter Student Commons / Collision Space".
7. **Guest band**: a diagonal blue band (rotated) with heading "مهمانان:" (Guests:) and two
   **circular** guest portraits + bilingual name/title under each:
   - فرامرز سماواتی / "Professor, Computer Science, University of Calgary"
   - حسین احمدی نژاد / "Engineering Leader and Chief Architect at Humanix"

## Assets (§2, ASSET_MAP)

Only the logo was supplied. The hero photo and 2 portraits are NOT separate files. Extract
placeholder crops FROM the reference poster with Pillow/skia (hero tower region ~x 380-720 y
0-560; portrait circles ~ the two faces in the band), save under
`examples/reference-poster/assets/` (hero.png, guest-samavati.png, guest-ahmadinejad.png),
and DOCUMENT in examples/reference-poster/ASSET_MAP.md that these are placeholder crops from
the reference, and that the template treats hero + portraits as CONFIGURABLE image variables
(a real deployment supplies its own). Copy the supplied logo into the example dir too. Never
modify examples/reference/* originals.

## Deliverable structure (task §9)
```
examples/reference-poster/
├── template.yaml        # root node tree, stable semantic node IDs
├── schema.yaml          # variable declarations (all content configurable)
├── formats.yaml         # square/portrait/story/landscape/a4 canvases + minimal patches
├── locales.yaml         # en + fa: direction, digits, font stacks, patches
├── preview-data.yaml    # renders standalone
├── data/
│   ├── poster.en.yaml
│   └── poster.fa.yaml
├── assets/              # logo + placeholder hero/portraits
├── ASSET_MAP.md
├── README.md            # usage: how to render all combos, how to swap content
└── outputs/final/       # curated final renders (10) committed
```

## Template requirements (§9)
- Real Arcavex engine only. Stable semantic node IDs (logo, org-caption, hero, headline,
  subtitle, datebox, date-value, time-value, venue-box, guests-band, guests-heading,
  guest[0]/guest[1] via repeat with key, guest-photo, guest-name, guest-title).
- Content/layout separated: headline, subtitle, date, time, venue, org caption, guest list
  (name/title/photo/facing) all configurable via schema variables.
- Bilingual en/fa with correct LTR/RTL (fa headline/subtitle/labels RTL; English venue/titles
  LTR runs shape correctly inside the RTL composition). Persian digits in fa via locale digits.
  Appropriate bundled fonts (Estedad/Lalezar display + Vazirmatn body for fa; Inter for en).
- Do NOT encode any language as positioned image text — all text is live text nodes.
- Use constraints + only-necessary format patches. Preserve hierarchy + recognizable
  composition across ratios WITHOUT forcing one layout into every ratio (landscape 16:9 will
  reflow — hero beside content differently than story 9:16 which stacks). Minimal, understandable
  patches.
- Guests via `repeat:` over a guest list with stable `key:`.
- Text stays readable for realistic long values (the English titles are long — must wrap/fit,
  not overflow).

## Formats (§9): square 1:1, portrait 4:5 (native), story 9:16, landscape 16:9, A4 portrait.
## Locales: en + fa. Generate ALL 10 combinations → examples/reference-poster/outputs/final/
   named `poster.<format>.<locale>.png` (+ optionally a4 as pdf). Do NOT commit failed iterations.

## Process
1. Extract assets, build the template incrementally, render portrait/fa first (closest to the
   reference), VIEW it, iterate until it recognizably matches the reference identity.
2. Then square/story/landscape/a4 × en/fa. VIEW each; fix overflow/overlap/RTL/crop issues via
   constraints or minimal patches — NOT arbitrary offsets hiding engine bugs (§10).
3. Keep it deterministic; keep all existing engine tests green (you are adding an example +
   maybe fixtures, not changing the engine — if you find a genuine ENGINE bug, report it to the
   orchestrator rather than papering over it in the template).
4. A test (tests/e2e/test_reference_poster.py) that all 10 combos compile+render exit 0 and
   layout-inspect reports no overflow/edge-collision on the final set.

## Acceptance
```
render all 10 combos → exit 0, curated into outputs/final/
arcavex layout inspect ... (no overflow/overlaps on final variants)
pytest tests -q  (all green)
```

## Exit criteria
A reusable bilingual IPEN template preserving the reference's visual identity renders all 5
formats × 2 locales through the real engine, each intentionally composed, text readable, RTL
correct, logo + diamond-grid hero + circular portraits + red boxes + blue guest band present;
the design matrix (docs/agent-runs/reference-poster-design-matrix.md) passes every row.

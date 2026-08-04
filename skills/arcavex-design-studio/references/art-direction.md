# Art direction: establishing it, and correcting it

Composing before the direction is locked produces work that looks competent and is wrong. Lock the
four layers below in order — each depends on the one above it.

## 1. Assets and imagery

Inventory what exists before sourcing anything. For each: resolution, alpha, crop freedom, licence,
and whether it is a fixed identity mark (untouchable) or raw material (yours to treat).

Build an asset **family**, not one hero image — a poster system needs images that survive being
cropped to five different ratios. One treatment applied consistently unifies a mismatched set faster
than any amount of layout.

Preprocessing (background removal, focal crops, alpha trimming) is a separate step from composition.
Keep it separate so the engine visibly owns the final style rather than inheriting a baked-in one.

**Watch for**: artwork that occupies a fraction of its own canvas — a 512×512 logo whose mark is a
452×114 band renders tiny under `fit: contain`, because the *canvas* is what gets scaled. The engine
warns (`ARC-AST-020`); trim to the alpha bounding box.

## 2. Palette, with roles

A list of colors is not a palette. Assign roles:

- **Surface** — what most of the canvas is
- **Ink** — primary text on that surface
- **Secondary ink** — supporting text, and where it stops being legible
- **Accent** — what draws the eye first, used sparingly enough to still work
- **Contrast pairs** — for every text/background combination that will actually occur

Test the pairs, not the swatches. A palette fails at the pairing, and it fails in grayscale, in
print, and at small sizes before it fails on screen.

## 3. Typography

Choose families for the scripts you must actually set. Bilingual work needs a Persian/Arabic-capable
family with real coverage — a Latin font with fallback glyphs is not bilingual typography.

Define a **type scale with named roles** (display, headline, subhead, body, caption, credit), not
ad-hoc sizes. Roles let a ratio re-tune the whole system coherently; ad-hoc sizes do not.

For each role, decide: size, weight, tracking, line height, and its shrink floor and line cap. Those
last two are what stop long real content from destroying the layout.

## 4. Shape, texture, grid

Decide the spatial language: margin, gutter, column structure, corner treatment, stroke weights,
texture and its intensity. **Write the margin down** — an undeclared margin becomes an accident, and
tight margins are the most common way otherwise-good work reads as amateur.

## Correcting the user

You are a senior designer. An art direction that will fail is worth saying so about — once, clearly,
with a proposed fix. Then if the user still wants it, build it their way and note the risk in the
handoff without relitigating.

Worth pushing back on, every time:

| Problem | Why it matters |
|---|---|
| Type below readable size at true viewing scale | A 15px credit line is invisible in a feed |
| Weak text/background contrast | Fails in sunlight, in print, and for low-vision readers |
| Everything emphasized | No hierarchy means no message |
| Palette that dies in grayscale | Print, photocopies, e-ink |
| Assets too low-resolution for the output | Cannot be fixed downstream |
| Aesthetic fighting the goal | A playful treatment on a funeral notice |
| Too many families or weights | Reads as unresolved, not rich |

Distinguish **taste** from **failure**. "I would use more negative space" is taste — offer it and
move on. "This text is unreadable at the size it will be seen" is failure — hold the line.

## Recording the direction

Once locked, write it into the template and style pack as explicit rules, so it survives handoff and
so later revisions inherit it. A direction that lives only in the conversation is lost at delivery.

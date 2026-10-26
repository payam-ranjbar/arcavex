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

For each role, decide: size, weight, tracking, the box height its line height needs, and its shrink
floor and line cap. Those last two are what stop long real content from destroying the layout.

### Readability floors (defaults)

Minimum rendered font size per role, in canvas px for a 1080 px wide feed or story canvas; for
other widths of those formats scale by `canvas width / 1080`. These are floors, not targets, and a
brand kit may raise or lower them. A 1080 px post or story fills a phone about 390 pt wide, so 30 px
on canvas is about 11 pt on screen, the usual minimum for text people must read (Apple HIG);
stories are seen for about two seconds, so their floors are higher.

| Role | Feed post (1080x1080 / 1080x1350) | Story / reel (1080x1920) |
|---|---|---|
| Headline / display | 72 px | 80 px |
| Facts (date, time, place) | 40 px | 44 px |
| Name | 44 px | 48 px |
| Role / affiliation | 32 px | 36 px |
| Body | 32 px | 36 px |
| Caption / credit | 28 px | 30 px |

Thumbnails and print have their own rules instead of the width scaling. Thumbnails (16:9 at
1280x720, judged at about 200-360 px wide in a grid): headline at least 10% of canvas height (72 px
at 720). Print (A4/A3 at arm's length): body at least 9 pt, facts at least 12 pt at print size; wall
posters read from 2 m need facts at least 24 pt.

## 4. Shape, texture, grid

Decide the spatial language: margin, gutter, column structure, corner treatment, stroke weights,
texture and its intensity. **Write the margin down** — an undeclared margin becomes an accident, and
tight margins are the most common way otherwise-good work reads as amateur.

## 5. Compositing photos into fields

Paint order is document order: the first child of a group is drawn at the bottom, later children
over it (a node's `z` changes that). So the order you write is the order you see.

Recipe for a photo blended into a patterned or textured field, bottom to top:

1. base: the surface colour (a `shape` or `path` node),
2. pattern or texture over the base,
3. the photo, with an alpha fade on the edge that meets the pattern,
4. type and marks.

Drawing the pattern after the photo covers the photo; that is the common failure.

Photos use `fit: cover` (fills the box, crops, keeps proportions). Never `fit: fill` on photography:
it stretches to the box and distorts faces. `contain` letterboxes; use it for logos and marks, not
photos.

Fades: the engine has no gradient alpha mask. Masks clip to a hard shape (`rounded_rect`, `circle`,
`diamond_grid`) and `style.opacity` is uniform. Pre-bake the fade into a PNG with an alpha channel
at the asset's full resolution, keep the script beside the asset so the fade can be regenerated, and
use the PNG with `fit: cover`. Example (Pillow):

```python
from PIL import Image, ImageOps
im = Image.open("photo.jpg").convert("RGBA")
w, h = im.size
band = int(h * 0.35)  # bottom 35% fades to transparent
alpha = Image.new("L", (w, h), 255)
alpha.paste(ImageOps.invert(Image.linear_gradient("L").resize((w, band))), (0, h - band))
im.putalpha(alpha)
im.save("photo-fade.png")
```

<!-- TODO(A9): replace the pre-baked fade with the built-in gradient mask once merged -->

Check the draft render before tuning: the pattern must be visible only where the photo has faded.

## Correcting the user

You are a senior designer. An art direction that will fail is worth saying so about — once, clearly,
with a proposed fix. Then if the user still wants it, build it their way and note the risk in the
handoff without relitigating.

Worth pushing back on, every time:

| Problem | Why it matters |
|---|---|
| Type below readable size at true viewing scale (floors table above) | A 15px credit line is invisible in a feed |
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

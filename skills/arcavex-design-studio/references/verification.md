# Verifying a design system

A warning-free render is **necessary and not sufficient**. Bad typography validates perfectly. The
engine checks that a design is well-formed; whether it is any good is your judgement, and this is
where you exercise it.

## The matrix

Cross **every format × every locale × at least two content profiles**:

- **Production copy** — realistic content
- **Boundary copy** — every field at its declared maximum

Add profiles for optional-field omissions, mixed scripts, long dates, or dense credits when the
campaign uses them. Report the actual pass count. A template verified on one cell is verified on one
cell.

## Per cell

1. `validate` — clean
2. **Look at the pixels** — iterate at `--dpi 96` (MCP: `dpi=96` on `arcavex_render_preview`),
   then check full resolution once before delivery. A print-DPI A2 preview is a multi-megabyte
   image you gain nothing from while composing.
3. `layout inspect` — resolved geometry
4. Render

## What to hunt

**Overlapping elements.** `layout inspect` reports collisions between siblings. It does **not**
compare nodes in different groups, so a real collision across two groups will not appear — check the
pixels too. Overlaps are classified: `content` is a genuine collision; `halo` is effect spill (a
shadow reaching over a neighbour) and usually intended.

**Tight margins.** The most common way otherwise-good work reads as amateur. Content crowding a
canvas edge or a neighbour looks like an error even when it technically fits. Hold the declared
margin and gutter system. Judge the **optical** edge — a glyph's ink, not its box — since text boxes
carry side bearing that makes tight spacing look tighter than the numbers suggest.

**Illegibility at real size.** Compute the rendered size at the actual viewing scale, not at the
canvas resolution. A 15px caption on a 2000px canvas is invisible in a feed.

**Weak contrast** between text and its true backdrop — the backdrop is whatever is actually behind
it, which may be an image, not the surface color.

**Overflow and shrink.** `layout inspect` reports overflow states a clean validation hides. Text that
shrank to its floor is a warning sign even when it fits: the design assumed content it did not get.

**Missing glyphs** — especially in the non-Latin locale.

**Broken hierarchy.** Step back from the pixels: does the eye land where the message needs it to? If
everything is emphasized, nothing is.

## Determinism

Re-render one representative cell and compare hashes. Identical inputs must produce identical bytes.
A mismatch means something non-deterministic entered the pipeline — an unseeded random, a timestamp,
a machine-dependent path — and it is a real finding, not noise.

```bash
arcavex render poster.yaml --format square -o a.png
arcavex render poster.yaml --format square -o b.png
# hashes must match
```

## Reporting

State plainly:

- Which formats and locales passed, and how many cells
- What content limits the template is verified for
- What remains **unverified** — an untested locale, an unrendered format, a content profile you
  skipped
- Any unverified factual copy

Distinguish **"rendered without errors"** from **"is good design"**. Only the first is machine-checkable,
and conflating them is how a clean report ships a bad poster.

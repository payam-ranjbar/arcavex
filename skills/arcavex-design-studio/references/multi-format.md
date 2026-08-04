# Every ratio is its own design problem

Arcavex renders one template into many formats. That is a production convenience, **not** permission
to design once and scale.

## Why scaling fails

A 9:16 story and a 16:9 thumbnail differ in more than proportion:

- **Reading distance and duration.** A story is held at arm's length for two seconds; an A4 poster is
  read on a wall; a thumbnail is judged at 200px wide in a grid.
- **Attention order.** Vertical formats read top-to-bottom; wide formats read left-to-right and
  support side-by-side blocks that stack badly in a column.
- **Content capacity.** A square can carry a subtitle a thumbnail cannot.
- **Safe areas.** Story formats lose the top and bottom to platform UI.

A layout scaled from one to another is optimal for none of them, and usually visibly wrong in at
least one.

## Per-ratio investigation

For **each** declared format, decide deliberately:

1. **What leads.** The hero image, the headline, or the mark — it is not always the same one.
2. **What is dropped.** Some formats cannot carry the full content contract. Decide what falls away,
   and encode it (`if:` / format patches), rather than letting it overflow.
3. **Structure.** Stacked, split, full-bleed, framed. Recompose; do not reflow.
4. **Type scale re-tune.** Roles keep their relationships; absolute sizes change. Re-check the
   smallest role against the real viewing size for *this* format.
5. **Crop.** The same image usually needs a different crop per ratio. Focal point, not centre.
6. **Safe area.** Declare and hold it — especially for story/reel formats.

Then verify that format on its own terms, not by analogy with a sibling that passed.

## Localization is the same problem again

A locale is not a text substitution:

- Farsi/Arabic is a **true RTL composition** — mirror the structure with logical start/end anchors,
  not right-aligned English.
- Text length shifts substantially between languages; the contract's maximums differ per locale.
- Digit policy is a decision (Latin vs Persian digits), not a default.
- Fonts differ per script, and so do their optical sizes at the same point size.

Every format × locale cell is a cell to verify. A template passing in `square/en` tells you nothing
about `story/fa`.

## Keeping it maintainable

Recomposing per ratio does not mean duplicating templates. Use format patches over one node tree so
content and identity stay single-sourced, and the differences remain explicit and reviewable.

When a format's structure diverges so far that patches become unreadable, that is a signal worth
reporting — sometimes two templates honestly beat one contorted one.

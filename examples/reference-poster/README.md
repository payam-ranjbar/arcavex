# Reference poster — bilingual IPEN event template

The flagship Arcavex example: a faithful, reusable reproduction of the supplied IPEN
"یک فنجان تجربه" (A Cup of Experience) event poster, rendered entirely by the engine across
**5 formats × 2 locales** from one node tree. Curated finals live in [`outputs/final/`](outputs/final/).

It demonstrates the split-template layout (`schema.yaml`, `formats.yaml`, `locales.yaml`,
`preview-data.yaml` sidecars), a keyed `repeat` over a guest list inside an `hstack`, the
`diamond_grid` and `circle` masks, locale direction/digit policies, per-format patches, and
fit policies that keep realistic long values readable.

## Render it

```sh
# Standalone (preview data, native 4:5 portrait)
arcavex render examples/reference-poster --format portrait

# A deployment render: English, Instagram square
arcavex render examples/reference-poster \
  --data examples/reference-poster/data/poster.en.yaml \
  --format square --locale en -o poster.square.en.png

# Farsi story (RTL, Persian digits)
arcavex render examples/reference-poster \
  --data examples/reference-poster/data/poster.fa.yaml \
  --format story --locale fa -o poster.story.fa.png

# Print: A4 at 300 dpi, PDF with correct physical page size
arcavex render examples/reference-poster \
  --data examples/reference-poster/data/poster.fa.yaml \
  --format a4 --locale fa -o poster.a4.fa.pdf
```

All 10 combos (`portrait square story landscape a4` × `en fa`) render clean; the acceptance
contract is pinned by `tests/e2e/test_reference_poster.py`.

## Composition (top → bottom)

| Node id | Role |
|---|---|
| `logo`, `org-caption` | IPEN mark + organisation name (English in both locales) |
| `hero` | Photo re-masked into the signature `diamond_grid` lattice, upper-right |
| `headline`, `subtitle` | Display headline + support line (localised, RTL-aware) |
| `date-value` | **Date box (زمان)** — pink, red-framed, date + time centred |
| `venue-box` | **Venue box (مکان)** — red-framed, English run in both locales |
| `guests-band-base`, `guests-band-accent` | The diagonal blue band (straight base + rotated accent centred on its top edge) |
| `guests-heading` | "Guests:" / «مهمانان:» riding the band |
| `guests-row` → `guest[<id>]` | Keyed `repeat` in a centred `hstack`: circular portrait, name, title |

Exactly **two** info blocks: the date box and the venue box, both with vertically and
horizontally centred content.

## Swap the content

Everything the poster shows is a schema variable — edit the data files, never the node tree:

- `data/poster.en.yaml` / `data/poster.fa.yaml` — complete per-locale deployments (headline,
  subtitle, day/month/time, venue, guest list). Render each with its matching `--locale`.
- `guests:` — ordered list of `{id, name, title, photo}`; `id` is the stable repeat key.
  Add a third guest and the centred hstack redistributes the row automatically.
- `hero` / `guests[].photo` — image variables; point them at your own assets (see
  [ASSET_MAP.md](ASSET_MAP.md) — the shipped hero/portraits are placeholder crops).

Locale mechanics worth copying: `day` is a *number*, so the `fa` digit policy renders ۱۵
automatically; strings that carry digits (`time`) are written in Persian digits in the fa
data. The venue and org caption stay English (LTR runs) inside the RTL composition, exactly
like the reference. Under `fa` the guest hstack flows right-to-left, so guest #1 sits at the
right — correct RTL reading order (photo/name/title pairs stay intact).

## Format reflow

`portrait` (4:5) is the authored geometry, matching the reference. The other formats reflow
via minimal `patch` sets in `formats.yaml`: `square`/`landscape` tighten the column and move
the venue box beside the date box; `story` enlarges the display type (2-line headline) and
deepens the band; `a4` retunes point sizes to print scale on the physically smaller 595 pt
page. The rotated band accent is anchored to the band's **top edge**, so the diagonal lands
correctly at every canvas height without per-format offsets.

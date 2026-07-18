# A bilingual template

Arcavex renders one node tree in multiple languages and multiple aspect ratios without duplicating
the layout. This tutorial walks the shipped **[reference poster](../../examples/reference-poster/)**
— the flagship IPEN event poster, rendered across **5 formats × 2 locales** from a single template —
and shows exactly how the locale, digit, RTL, font, data-overlay, and per-format-patch machinery fits
together. The reference for each construct is [template-schema.md](../template-schema.md#locales-data-layering-and-patches).

Render it yourself first — standalone (preview data, native 4:5 portrait), then a Farsi deployment:

```console
$ arcavex render examples/reference-poster --format portrait -o poster.png
inferred: data=preview_data
Rendered poster.png

$ arcavex render examples/reference-poster \
    --data examples/reference-poster/data/poster.fa.yaml \
    --format square --locale fa -o poster.square.fa.png
inferred: data_overlay=data.fa.yaml
Rendered poster.square.fa.png
```

## The split layout

The reference poster is a [split template](../template-schema.md#split-templates): each section is
its own sidecar, which keeps the node tree readable.

```text
reference-poster/
├── template.yaml       # the node tree (logo, hero, headline, date/venue boxes, guest band…)
├── schema.yaml         # variables — everything the poster shows is a declared input
├── formats.yaml        # square / portrait / story / landscape / a4 + per-format patches
├── locales.yaml        # en + fa: direction, digits, font handling
├── preview-data.yaml   # renders standalone
└── data/               # poster.en.yaml, poster.fa.yaml — complete per-locale deployments
```

## Declaring locales

`locales.yaml` (its top-level mapping *is* the template's `locales` section) is deliberately small —
the composition is locale-stable, and each locale only flips direction, digit policy, and fonts:

```yaml
en:
  direction: ltr

fa:
  direction: rtl
  digits: fa
  # No font overrides on purpose: every Farsi-bearing node already declares a Persian-capable
  # first family (Lalezar/Vazirmatn), and the always-English runs (org caption, venue, guest
  # titles) must keep their Latin face — a blanket Inter→Vazirmatn override would restyle them.
```

That font comment is the hard-won lesson of the example: a blanket family substitution in the locale
would have restyled the English runs that are *supposed* to stay Latin. Because each node already
names a Persian-capable first family, `fa` needs no `fonts:` override at all.

## Direction and logical edges

Setting `direction: rtl` at the root flows through every undirected group (direction inherits from
the nearest enclosing group that declares one — [ADR-0002](../adr/0002-direction-inheritance-and-data-layering.md)).
That is what makes the composition *mirror* rather than just relabel:

- Anchors written with the **logical** `start`/`end` edges resolve to right/left according to the
  resolved direction, so a `start`-anchored element sits on the reading-order side in both locales.
- An `hstack` mirrors automatically under RTL: the guest row's first guest sits at the **right** in
  `fa` (correct reading order), at the left in `en` — from the same `repeat`.

## Digits: numbers vs. strings

The digit policy (`digits: fa`) maps **numeric** values to Persian digits — but never touches string
content. The example leans on this precisely:

```yaml
day: 15            # a NUMBER → renders as ۱۵ under fa automatically
time: "۱۷:۰۰"      # a STRING carrying digits → written in Persian digits in the fa data
```

So `day` localizes for free, while `time` (a string with a colon) is localized in the data, not by
the policy. This is the intended split: declare truly numeric content as numbers and let the policy
do the work; keep formatted strings (times, phone numbers) as data you localize per locale.

## Data layering: overlays and sidecars

`data/poster.en.yaml` and `data/poster.fa.yaml` are **complete** deployments — render each with its
matching `--locale`. Note the Farsi file localizes the strings (`headline`, `subtitle`, guest
`name`s) while `org_caption` and `venue` stay English LTR runs inside the RTL composition, exactly
like the reference.

[Effective data](../template-schema.md#locales-data-layering-and-patches) resolves in four layers
(later wins): template `preview_data`/defaults → template `locales.<L>.data` overlay → the `--data`
file → a `data.<L>.yaml` sidecar next to it. Both overlay applications are reported as
`inferred: data_overlay=…` breadcrumbs, so you always know a locale layer was applied.

## Per-format patches: reflow, don't stretch

`portrait` (4:5) is the authored geometry. The other four formats reflow through **minimal `set`
patches** in `formats.yaml` — each op retunes a size, gap, or anchor for the new frame, never an
arbitrary offset hiding a bug:

```yaml
square:
  canvas: {width: 1080px, height: 1080px, dpi: 96}
  patch:
    - set: nodes.hero.constraints.size.h
      value: 46%                                   # hero gives up height on the short canvas
    - set: nodes.date-value.constraints.anchor.top
      value: …                                     # venue box moves BESIDE the date box (one row)
```

To see the resolved effect of the format and locale layers — and which layer produced each value —
ask `template inspect --resolved`:

```console
$ arcavex template inspect examples/reference-poster --resolved --format square --locale fa
```

## Render all ten combinations

```console
$ for f in portrait square story landscape a4; do
    for l in en fa; do
      arcavex render examples/reference-poster \
        --data examples/reference-poster/data/poster.$l.yaml \
        --format $f --locale $l -o poster.$f.$l.png
    done
  done
```

The curated finals ship under
[`examples/reference-poster/outputs/final/`](../../examples/reference-poster/outputs/final/), and the
acceptance contract (all ten render clean, no overflow/edge-collision, deterministic) is pinned by
`tests/e2e/test_reference_poster.py`. The design-review matrix
([reference-poster-design-matrix.md](../agent-runs/reference-poster-design-matrix.md)) records the
10/10 visual pass.

## Next

- The full locale/data/patch reference → [template-schema.md](../template-schema.md#locales-data-layering-and-patches).
- The example's own README (composition table, how to swap content) →
  [examples/reference-poster/README.md](../../examples/reference-poster/README.md).

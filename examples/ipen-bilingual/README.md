# ipen-bilingual — golden case #2

A simplified bilingual event poster that renders **Farsi (rtl)** and **English (ltr)** across
**square / story / A4** from one template. It is the acceptance artifact for Phase 2's layout,
text, and locale features; it is deliberately *not* the full reference reproduction.

## Render it

```bash
# English, square
arcavex render examples/ipen-bilingual/template.yaml \
  --data examples/ipen-bilingual/data.yaml --format square --locale en -o ipen-en-square.png

# Farsi, A4 (300 dpi -> ~2480x3508 px)
arcavex render examples/ipen-bilingual/template.yaml \
  --data examples/ipen-bilingual/data.yaml --format a4 --locale fa -o ipen-fa-a4.png

# Explain the geometry, or overlay it
arcavex layout inspect examples/ipen-bilingual/template.yaml \
  --data examples/ipen-bilingual/data.yaml --format square --locale fa --json
arcavex render ... --debug -o ipen-debug.png
```

`--data data.yaml --locale fa` loads `data.yaml`, merges the sibling `data.fa.yaml` overlay,
and applies the `fa` locale (rtl direction, Persian digits, font override).

## What it exercises

| Feature | Where |
|---|---|
| Locale direction (rtl/ltr) | `locales.fa.direction` → the root group's default direction |
| Persian digits | `locales.fa.digits: fa` → `day` (a number) renders as `۱۵`; `time` comes localized from the overlay |
| Locale font override | `locales.fa.fonts: {Inter: [Vazirmatn, Inter]}` |
| Data overlay | `data.fa.yaml` replaces the localised strings (mapping merge) |
| Format patch | `formats.a4.patch` enlarges the hero band on the tall A4 sheet |
| Diamond-grid mask | `hero` image → `mask: {component: diamond_grid, ...}` (gutters show the background) |
| Rotation | `accent-bar` → `transform: {rotate: -4}` |
| Sibling anchors | every lower element anchors below the previous one (`title.bottom`, …) |
| Logical start/end | `anchor: {start: parent.start+56pt}` (right-inset in rtl, left-inset in ltr) |
| Vstack | the date card's two lines flow in a `layout: vstack` group |
| Fit policies | `title` shrink_to_fit, `subtitle`/`venue` wrap/truncate with `max_lines` |

Renders are deterministic (bundled fonts only, no wall-clock): the same target re-renders
byte-identically.

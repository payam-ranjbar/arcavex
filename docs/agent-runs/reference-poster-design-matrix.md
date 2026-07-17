# Reference poster — design review matrix
Reviewer: design-review subagent (Sonnet) | Date: 2026-07-16 | Commit under review: 81f2081

| # | Format | Locale | Identity | Composition | Readability | RTL/Locale | Collisions | Verdict |
|---|--------|--------|----------|-------------|-------------|------------|------------|---------|
| 1 | portrait | fa | ok — logo/caption, diamond-grid hero, red date+venue boxes, blue band, 2 circular portraits all present | ok — matches reference geometry closely, native ratio | ok — all text legible, good contrast | ok — Farsi shapes connected (no tofu), RTL alignment natural, Persian digits ۱۵/۱۷:۰۰, venue/caption clean LTR runs | ok — no overlaps or edge clipping | PASS |
| 2 | portrait | en | ok — same elements, headline "A Cup of Experience" | ok — same well-balanced portrait geometry | ok — no truncation, good contrast | n/a (LTR) | ok | PASS |
| 3 | square | fa | ok — all signature elements present | ok — date/venue boxes reflow side-by-side, hero column narrowed; deliberately recomposed, no dead zones | ok — text legible; "مهمانان:" sits on the light triangle above the band diagonal (documented exception) with adequate black-on-white contrast | ok — connected glyphs, correct RTL, Persian digits, English venue/caption stay LTR | ok — no clipping, portraits don't overlap text | PASS |
| 4 | square | en | ok | ok — same side-by-side reflow, well composed | ok — "Guests:" heading on light triangle, adequate contrast (documented exception) | n/a | ok | PASS |
| 5 | story | fa | ok | ok — tall column deepens band, enlarges display type into two lines; deliberate, no dead zones | ok — headline breaks after "فنجان" (natural phrase break, not mid-word); all text legible | ok — RTL correct, digits correct, LTR runs clean | ok — no collisions with deepened band | PASS |
| 6 | story | en | ok | ok — headline "A Cup of" / "Experience" breaks naturally at phrase boundary | ok — legible, good contrast | n/a | ok | PASS |
| 7 | landscape | fa | ok | ok — hero right ~35%, date+venue boxes side-by-side beneath headline, band spans bottom; intentionally recomposed for 16:9, no crowding | ok — all text legible incl. two-line venue box | ok — RTL correct, Persian digits, "مهمانان:" white-on-blue with strong contrast | ok — no overlap between hero, boxes, or band | PASS |
| 8 | landscape | en | ok | ok — mirrored LTR layout, well balanced | ok — legible throughout | n/a | ok | PASS |
| 9 | a4 | fa | ok | ok — portrait-like print geometry, point sizes retuned to page scale, hierarchy preserved | ok — legible at print scale, no crowding | ok — RTL correct, Persian digits, LTR runs clean | ok — no collisions | PASS |
| 10 | a4 | en | ok | ok — same print geometry, well composed | ok — legible | n/a | ok | PASS |

## Findings
### P1 (blocks a row's PASS)
- None.

### P2 (should fix, doesn't block)
- None found — no readability, collision, or RTL defects across the 10 renders.

### P3 (nice-to-have)
- Venue box text renders as "Hunter Student Commons — Collision Space" (single line joined with an em dash before wrapping) in all 10 renders, where the reference shows the building and room name as two visually distinct lines with no punctuation between them. This is a data-content choice (`venue` field in `data/poster.*.yaml`), not a template/engine defect, and doesn't hurt readability — but a future content edit could split it into two schema fields (e.g. `venue-building` / `venue-room`) to match the reference's cleaner two-line look more exactly.
- In the `square` format only, the guest-band heading ("مهمانان:"/"Guests:") sits above the band diagonal on white rather than on blue — this is a documented, accepted exception per the brief, called out here only for completeness, not as a defect.

## Summary
All 10 format×locale combinations pass. The reproduction is faithful to the reference's visual identity (logo/caption, diamond-grid hero, red-framed pink date box, red-framed venue box, diagonal blue guest band with circular portraits) in every render, and each format is genuinely recomposed for its aspect ratio rather than stretched — square and landscape reflow the date/venue boxes side-by-side, story deepens the band and stacks the display headline, a4 retunes to print scale. RTL/Farsi rendering is correct throughout (connected glyphs, natural alignment, Persian digits, clean embedded LTR runs for venue/org caption/titles), and no row shows truncated text, illegible sizing, inadequate contrast, or element collisions. 10/10 PASS, zero P1s, zero P2s.

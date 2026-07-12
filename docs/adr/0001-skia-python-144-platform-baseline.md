# ADR 0001 — skia-python 144 platform baseline and textlayout binding constraints

- Status: accepted
- Date: 2026-07-12
- Phase: -1 (feasibility)

## Context

The specification (§11 Phase -1) requires verifying skia-python, SkParagraph shaping,
pinned local fonts, RuntimeEffect/SkSL, raster + PNG output, PDF physical sizing, and
deterministic CPU rendering before core implementation.

Feasibility was executed on Windows 11 x86-64 with CPython 3.12.13 and
**skia-python 144.0.post2** (the current stable release; older stable lines 87.x predate
the `skia.textlayout` module entirely).

All nine probes passed: import/version, textlayout availability, pinned font loading
(Inter, Vazirmatn, Estedad, Lalezar from a local directory via `TypefaceFontProvider`),
mixed Farsi/English shaping with correct joined RTL glyphs, SkSL `RuntimeEffect`
compilation, raster surface + PNG export, byte-identical repeated renders, PDF with
physical page size (A4 in points), and PNG decode of the reference poster.

## Constraints discovered

skia-python 144 exposes a deliberately small subset of SkParagraph:

1. `ParagraphStyle`: only `setStrutStyle`, `setTextAlign`, `setTextStyle`.
   **No `setTextDirection`, no max-lines, no ellipsis.**
2. `Paragraph`: `layout`, `paint`, and scalar metrics (`Height`, `Width`,
   `LongestLine`, `MaxIntrinsicWidth`, `MinIntrinsicWidth`, `AlphabeticBaseline`,
   `IdeographicBaseline`, `ExceedMaxLines`). **No per-line metrics, no
   `getRectsForRange`, no unresolved-glyph count.**
3. `ParagraphBuilder.make(style, fontCollection, unicode)` requires an explicit
   `skia.Unicode` instance (ICU-backed).
4. `FontCollection` exposes only `setDefaultFontManager`. Registering a
   `TypefaceFontProvider` as the *default* manager confines every fallback lookup to
   bundled fonts, which is exactly the determinism posture §4.3 requires.
5. On Windows, ICU requires `icudtl.dat` next to the *base* interpreter executable.
   The wheel ships the file in `site-packages`; it is not auto-discovered in venvs
   whose base interpreter directory lacks it.

## Decision

1. **Pin skia-python `>=144.0,<145` as the rendering platform.** SkParagraph remains the
   single text shaper (spec §4.3); no second shaper is introduced.
2. **Base paragraph direction is controlled with Unicode BiDi isolates** (U+2066 LRI /
   U+2067 RLI / U+2069 PDI) emitted by the Arcavex text service around paragraph text,
   plus mapping of logical `start`/`end` alignment to `kLeft`/`kRight` according to the
   resolved direction. This is applied by the text service only — template authors keep
   writing plain `direction: rtl`.
3. **Fit policies (`shrink_to_fit`, `truncate`, `wrap`, `overflow`) are implemented in
   the Arcavex text service** on top of scalar paragraph metrics with the spec's ≤ 8
   measurement iterations, rather than relying on unexposed SkParagraph
   max-lines/ellipsis features.
4. **Missing-glyph diagnostics are computed by Arcavex** by probing
   `Typeface.unicharToGlyph` across the resolved font chain at compile/measure time,
   since the binding exposes no unresolved-glyph API.
5. **`arcavex doctor` verifies ICU availability** and reports the `icudtl.dat`
   remediation (copy from `site-packages` next to the base interpreter) as an
   actionable diagnostic. Installation docs cover it.
6. Persian digit rendering continues to use the variable layer (`locale_digits`),
   unaffected by these binding limits.

## Consequences

- The public template contract (direction, alignment, fit policies, max lines) is
  unchanged from the spec; the limitations are absorbed inside `services/text/`.
- Some inspection data (per-line boxes) is approximated from paragraph-level metrics;
  layout inspection reports paragraph bounds, baseline, and measured line count rather
  than per-glyph boxes. This is documented in `docs/known-limitations`.
- If a future skia-python release restores richer Paragraph bindings, the text service
  can adopt them without changing template semantics.
- ARM64 (linux-aarch64/macos-arm64) wheels exist for skia-python 144 upstream but were
  not testable on this Windows x86-64 development machine; CI remains the verification
  point (spec §8.5). Recorded as a known limitation, not silently claimed.

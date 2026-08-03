# ARC-EXT-050 — Effect bounds-expansion is dishonest

A raster effect paints visibly outside the outward margin it declares via bounds_expansion, so the layout solver would not reserve enough paint region and the output would be clipped in the real pipeline.

**Typical fix:** Grow bounds_expansion to cover the effect's real outward spread on every side.

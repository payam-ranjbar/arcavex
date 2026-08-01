# Style Lab filters

Four deterministic Arcavex raster effects used by the Graphic Style Lab example:

- `swiss-cut` — limited ink, clean tonal steps, and a registered signal color.
- `xerox-pulse` — threshold copy, scan texture, dropout, and slice jitter.
- `cinema-emulsion` — split-tone curve, highlight halation, vignette, and grain.
- `riso-register` — four-ink ordered screen, plate drift, and paper texture.

Every effect preserves source alpha, stays inside its node bounds, uses only Arcavex's seeded RNG,
and is covered by the included golden harness.

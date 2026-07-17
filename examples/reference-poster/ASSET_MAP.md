# Asset map — reference-poster

The template treats the hero photo and guest portraits as **configurable image
variables** (`hero`, and `photo` per guest). A real deployment supplies its own
files; the assets below are placeholders so the example renders standalone.

| File | Dimensions | Origin | Role |
|---|---|---|---|
| `logo.png` | 1024×1024 | **Supplied asset**, copied verbatim from `examples/reference/logo.png`. | IPEN wordmark, top-left. The one non-placeholder asset. |
| `hero.png` | 292×335 | **Placeholder crop** from `examples/reference/reference-poster.png` (tower-base region, box `(428,270,720,605)`). | Hero photo — lit tower + fireworks. Re-masked into the `diamond_grid` lattice by the engine. |
| `guest-samavati.png` | 124×124 | **Placeholder crop** from the reference poster (left portrait, box `(88,606,212,730)`). | Guest[0] portrait, re-masked into a circle. |
| `guest-ahmadinejad.png` | 124×124 | **Placeholder crop** from the reference poster (right portrait, box `(296,602,420,726)`). | Guest[1] portrait, re-masked into a circle. |

## Notes

- The hero crop was taken from the tower-base region rather than the full
  fireworks band because that region is mostly solid photographic content, so
  re-applying the `diamond_grid` mask produces clean lattice cells instead of
  double-gridding the reference's baked-in gutters.
- Portrait crops are square bounding boxes around each face; the template's
  `circle` mask clips the band-colored corners at render time.
- `examples/reference/*` originals are **never modified** — these are copies and
  derived crops written only into this example's `assets/` directory.
- To deploy with real photos: drop replacements at the same paths (or point the
  `hero` / `guests[].photo` data variables at other ingested assets) — no
  template edit required.

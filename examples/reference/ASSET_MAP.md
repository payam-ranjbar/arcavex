# Reference asset map

Assets supplied with the original task, preserved unchanged.

| File | Size | Dimensions | Role |
|---|---|---|---|
| `reference-poster.png` | 900,036 B | 720×914 | The reference event poster to reproduce as a reusable Arcavex template. IPEN "یک فنجان تجربه" bilingual event poster: Farsi headline/subtitle, red-outlined date/location boxes, diamond-grid masked tower photo (fireworks over a tower), diagonal blue guest band with two circular guest portraits and bilingual captions, IPEN logo top-left. |
| `logo.png` | 281,271 B | 1024×1024 | The IPEN logo (green/red skewed squares with white "IPEN" wordmark, white background). Used top-left on the poster. This exact asset must be used by the recreated template. |

Notes:

- The poster embeds two guest portrait photographs and a tower/fireworks photo that
  were **not** supplied as separate assets. The recreated template treats portraits and
  the hero photo as configurable image variables; placeholder-safe crops extracted from
  the reference poster are stored under `examples/reference-poster/assets/` and
  documented there.
- The logo is supplied on a white (opaque) background, not transparency; the template
  places it on a white canvas region so this is faithful to the reference.

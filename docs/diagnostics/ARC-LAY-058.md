# ARC-LAY-058 — Text shrank below its declared size

A text node using 'shrink_to_fit' converged by rendering at a smaller font size than the style declares, because the resolved box could not hold the declared size. This is a warning: the render is correct, but the same headline renders smaller in one format than in another. The message names the node, the format, the declared size and the rendered size.

**Typical fix:** Enlarge the box or shorten the copy so the declared size fits, or accept the shrink. Run validate/render with --strict to make this a build failure.

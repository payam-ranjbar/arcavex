# ARC-LAY-051 — Text fit did not converge

A 'shrink_to_fit' text node could not be made to fit even at its smallest allowed size within the ≤ 8 measurement iterations, so it still overflows. This is a warning: the text is clipped or allowed per the overflow policy and the render still succeeds.

**Typical fix:** Lower min_size so a smaller, fitting size exists, enlarge the box, or switch the policy to 'truncate'. Note the direction: 'min_size' is the floor of the shrink search, so raising it removes the smallest candidates, which are the only ones that could still fit.

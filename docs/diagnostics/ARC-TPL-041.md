# ARC-TPL-041 — Invalid text fit policy

A text node's 'fit' block has an invalid value: 'policy' must be wrap/shrink_to_fit/truncate and 'overflow' must be clip/allow/error.

**Typical fix:** Correct the fit policy or overflow value; add 'min_size' for shrink_to_fit.

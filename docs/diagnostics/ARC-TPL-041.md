# ARC-TPL-041 — Invalid text fit policy

A text node's 'fit' block has an invalid value: 'policy' must be wrap/shrink_to_fit/truncate, 'overflow' must be clip/allow/error, and 'balance' must be true or false.

**Typical fix:** Correct the fit policy, overflow, or balance value; add 'min_size' for shrink_to_fit.

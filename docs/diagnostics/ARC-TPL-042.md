# ARC-TPL-042 — Malformed path data

A path node's 'd' is missing, empty, or not valid SVG path data: it does not start with a move (M/m), uses a letter that is not one of M L H V C S Q T A Z, is short of numbers for a command, or gives an arc a flag other than 0 or 1. The hint quotes the offending token and its offset. Coordinates are pixels from the node box's top-left corner, converted to points at the format's dpi like any bare-px length.

**Typical fix:** Fix the quoted token. Write commands as a letter followed by its numbers, e.g. 'M 0 0 L 100 0 L 100 100 Z'; upper-case is absolute, lower-case relative.

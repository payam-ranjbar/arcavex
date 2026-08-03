# ARC-LAY-057 — Text still exceeds max_lines at the shrink floor

A 'shrink_to_fit' text node reached its 'min_size' floor and the text still wraps onto more lines than 'max_lines' allows, while each line does fit the box width. The binding constraint is the line cap, not the box, so this is reported separately from ARC-LAY-050: the message names the measured line count, the cap, and the floor reached rather than a width x height pair, because the measured height is simply what that many lines occupy.

**Typical fix:** Widen the box so the text needs fewer lines, lower min_size so it can shrink further, or raise max_lines. Enlarging the box height cannot help.

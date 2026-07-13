# ARC-LAY-012 — Invalid anchor offset

An anchor offset could not be parsed into a fixed distance, usually a malformed unit (missing number or unknown suffix). '{{ }}' expressions ARE evaluated inside constraint strings before the offset is parsed, so a leftover brace means a malformed or nested expression rather than an unsupported feature.

**Typical fix:** Use an offset such as '+20px', '+20pt', or '-6mm'. Per-item offsets from expressions work — e.g. 'top: parent.top+{{ loop.index * 90 }}pt' — as long as the expression resolves to a numeric distance.

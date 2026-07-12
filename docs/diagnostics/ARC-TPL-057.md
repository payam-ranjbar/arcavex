# ARC-TPL-057 — repeat key derived from index

A repeat key is derived from loop.index, so reordering the data changes node IDs.

**Typical fix:** Prefer a stable field such as '{{ item.id }}' when the data has one.

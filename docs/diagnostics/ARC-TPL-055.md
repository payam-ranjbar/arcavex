# ARC-TPL-055 — repeat missing 'key'

A repeat construct requires a stable 'key' expression for stable expanded IDs.

**Typical fix:** Add 'key: "{{ item.id }}"' (or '{{ loop.index }}' if order is stable).

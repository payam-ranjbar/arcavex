# ARC-TPL-051 — Unknown field

A style, paragraph, fit, constraints, size, or run block contains a field name the compiler does not recognize (often a typo such as 'font_wieght'). Unknown fields are rejected rather than silently ignored, so a misspelled property cannot quietly do nothing.

**Typical fix:** Fix the field name; the diagnostic lists the valid fields for that block.

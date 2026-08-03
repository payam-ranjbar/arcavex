# ARC-TPL-051 — Unknown field in a node sub-block

A node sub-block — style, paragraph, fit, constraints, size, run, transform, mask, padding, or a repeat/if construct — contains a field name the compiler does not recognize (often a typo such as 'font_wieght'). Unknown fields are rejected rather than silently ignored, so a misspelled property cannot quietly do nothing. The node top level and the template-level scopes carry their own codes: ARC-TPL-064 (node), ARC-TPL-065 (template root), ARC-TPL-066 (format/canvas), ARC-TPL-067 (variable declaration), and ARC-TPL-068 (effect entry).

**Typical fix:** Fix the field name; the diagnostic lists the valid fields for that block.

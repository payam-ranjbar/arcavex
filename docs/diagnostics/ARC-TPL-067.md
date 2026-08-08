# ARC-TPL-067 — Unknown variable-declaration field

A 'variables.<name>' declaration carries a field the engine does not read. A declaration holds 'type', 'required', 'default', 'enum', and 'doc'.

**Typical fix:** Correct the field name; describe the variable with 'doc' and constrain it with 'type'/'enum'.

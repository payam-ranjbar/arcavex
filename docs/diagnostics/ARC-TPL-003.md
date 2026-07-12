# ARC-TPL-003 — Template root is not a mapping

A template file must be a YAML mapping with sections such as 'root:' and 'formats:'.

**Typical fix:** Make the top level a mapping, not a list or scalar.

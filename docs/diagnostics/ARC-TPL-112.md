# ARC-TPL-112 — Data key matches no declared variable

A 'set_data' or 'import_data' top-level key does not correspond to any variable the template declares, so the value is written but no template expression ever reads it — usually a typo (for example 'titel' for 'title'). This is a warning, not an error, because deliberately-extra data can be legitimate.

**Typical fix:** Check the key against the template's declared variables (from 'template inspect'); fix the name, or ignore the warning if the extra data is intentional.

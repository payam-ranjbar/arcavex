# ARC-TPL-111 — Invalid data keypath

A 'set_data' keypath is empty, or one of its dotted segments descends into a value that is not a mapping (for example addressing 'contact.email' when 'contact' is already a scalar string). Only mappings can be traversed.

**Typical fix:** Use a dotted keypath whose intermediate segments are mappings; clear the offending scalar first, or choose a different path.

# ARC-EXT-022 — Extension component does not match its contract

A component class does not subclass the contract its kind requires, or its declared name/format attribute does not match the manifest name.

**Typical fix:** Subclass the arcavex.sdk contract for the kind, and set the class name/format attribute to the manifest name so the two agree.

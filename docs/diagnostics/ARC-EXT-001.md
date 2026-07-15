# ARC-EXT-001 — Duplicate component name

Two components claim the same name for one contract kind — an extension component shadowing a built-in or another added extension. Caught at 'ext validate' and 'ext add' (and again by the loader at start), naming both providers: the incumbent as a built-in or by its extension name, and the newcomer by its extension and class.

**Typical fix:** Component names are globally unique per kind; rename the extension's component (and its manifest name) to one that is not already registered.

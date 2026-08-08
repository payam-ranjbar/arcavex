# ARC-EXT-032 — Extension shader failed to compile

A component's SkSL shader (its 'SKSL' source) did not compile, so it would crash at render time.

**Typical fix:** Fix the SkSL source; the error message reports the offending line.

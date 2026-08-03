# ARC-RND-032 — Cannot remove a bundled font family

'arcavex font remove' named a family that ships with the engine. Bundled families back the default font stacks, so removing one would break templates that never opted into anything unusual, and the files would return on the next reinstall.

**Typical fix:** Only families added with 'arcavex font add' can be removed; 'arcavex font list' marks which families are bundled and which are installed.

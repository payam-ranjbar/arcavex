# ARC-TPL-061 — repeat and if on the same node

A single child declares both a 'repeat' and an 'if'. Applying both to one entry is ambiguous — whether the condition gates each iteration or the whole loop — so rather than silently pick one, the compiler asks you to nest them explicitly. A construct's 'node' is built directly (it is not itself scanned for nested constructs), so the inner construct must live inside a group's 'children' list.

**Typical fix:** Nest through a wrapper group: make the repeat's 'node' a group whose 'children' list holds the 'if' construct (the condition gates each item), or make the if's 'node' a group whose 'children' list holds the 'repeat' construct (the condition gates the whole loop).

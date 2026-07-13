# ARC-TPL-061 — repeat and if on the same node

A single child declares both a 'repeat' and an 'if'. Applying both to one entry is ambiguous — whether the condition gates each iteration or the whole loop — so rather than silently pick one, the compiler asks you to nest them explicitly.

**Typical fix:** Nest the constructs: make the 'if' construct the repeat's 'node' (the condition then gates each item), or put the 'repeat' construct inside the if's 'node' (the condition gates the whole loop).

# ARC-TPL-064 — Unknown node field

A node's top level carries a field the compiler never reads. This is the scope where an invented field is most damaging: it validates clean, does nothing, and the author keeps building on the belief that it works. Arcavex has no per-node 'condition' (gate a node with the structural 'if:' / 'node:' construct), no node-level paint fields (they live in 'style:'), and no node-level geometry fields (they live in 'constraints:' and 'transform:').

**Typical fix:** Read the hint: it names where a wrong-scope field actually belongs, or which node kind owns it, and otherwise lists the valid fields for this node's kind.

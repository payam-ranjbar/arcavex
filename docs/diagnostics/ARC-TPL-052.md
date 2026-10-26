# ARC-TPL-052 — Retired: stacks are supported

Reserved from the build that had no stack layout; no current build raises it. A group with 'layout: vstack' or 'layout: hstack' lays out its children with 'gap', 'padding', 'main_align' and 'cross_align', mirrors under rtl, and sizes to its children with 'h: fit_content'.

**Typical fix:** Put variable-height siblings in a 'layout: vstack' group instead of chaining '<node>.bottom+N' anchors; a format patch can override its 'gap'.

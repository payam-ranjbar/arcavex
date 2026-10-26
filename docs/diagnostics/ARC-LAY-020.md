# ARC-LAY-020 — fit_content on a node with no content to size to

'fit_content' sizes a text node to its text and a stack (a group with 'layout: vstack' or 'hstack') to its children. An anchored group, an image or a shape has no intrinsic size.

**Typical fix:** Give the node an explicit size or an aspect, or turn the group into a stack.

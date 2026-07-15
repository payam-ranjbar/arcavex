# ARC-AST-004 — Image asset escapes the template directory

An image node's resolved asset path points outside the template's own directory — via a '..' segment or a symlink that leads out of it. Template-relative files must stay within the template directory (spec §8.3); the check runs on the fully resolved path, so it also catches a symlink whose target is elsewhere.

**Typical fix:** Move the asset inside the template directory and reference it with a relative path that does not climb above the template root.

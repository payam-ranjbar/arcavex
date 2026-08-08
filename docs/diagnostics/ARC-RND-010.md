# ARC-RND-010 — Font family not available

A text node requests a font family the engine has not loaded. Rendering is confined to the bundled families plus any installed under the Arcavex home — system fonts are never consulted, because determinism requires it — so a typeface that is merely installed on the operating system will not resolve. The name must be the font's FAMILY (e.g. 'Lateef'), which often differs from its file name.

**Typical fix:** Use one of the families the hint lists, or install the typeface with 'arcavex font add <path/to/font.ttf>', which reports the exact family name to write. 'arcavex font list' shows every available family and the install directory.

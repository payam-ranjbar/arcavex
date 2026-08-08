# ARC-RND-011 — Missing glyph

A text run contains a code point that no loaded font can render, so it would paint as a tofu box. Rendering is confined to the loaded fonts for determinism, so the shaper never falls back to a system font. This is a warning; the render proceeds.

**Typical fix:** Install a font covering the reported code points with 'arcavex font add <path/to/font.ttf>', or remove the unsupported characters from the text.

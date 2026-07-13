# ARC-RND-011 — Missing glyph

A text run contains a code point that no bundled font can render, so it would paint as a tofu box. Rendering is confined to bundled fonts for determinism, so the shaper never falls back to a system font. This is a warning; the render proceeds.

**Typical fix:** Add a font that covers the reported code points under library-seed/fonts, or remove the unsupported characters from the text.

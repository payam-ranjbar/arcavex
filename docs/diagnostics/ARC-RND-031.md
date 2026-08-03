# ARC-RND-031 — Font file is not a usable typeface

'arcavex font add' was given a file the shaper cannot read as a TrueType font, either because of its extension or because Skia could not parse its contents. Such a file is refused rather than installed, since it would sit in the font directory providing no family and silently fail to resolve.

**Typical fix:** Install a .ttf file the engine can read; re-download or re-export the font, converting from another format (.otf, .woff2) to TrueType first.

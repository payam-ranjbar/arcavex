# ARC-AST-003 — Image asset exceeds a decode guard

An image is larger than a decode guard allows — too many source bytes, too many decoded pixels, or a disallowed format. The guard is enforced against the image header before any decompression, so a decompression bomb never gets decoded.

**Typical fix:** Reduce the image's dimensions or file size, or convert it to an allowed raster format (PNG, JPEG, GIF, BMP, or WEBP).

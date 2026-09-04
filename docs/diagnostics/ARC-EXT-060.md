# ARC-EXT-060 — Extension scaffold, add, or remove target problem

'ext scaffold' will not write into a non-empty directory; 'ext add' could not copy the extension into the Arcavex home; or 'ext remove' dropped the extension's record but could not delete its stored copy (nothing loads from that directory any more).

**Typical fix:** Choose a new or empty scaffold directory, ensure the Arcavex home is writable, or delete the leftover directory the message names by hand.

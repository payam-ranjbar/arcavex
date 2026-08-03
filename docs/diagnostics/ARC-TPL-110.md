# ARC-TPL-110 — Template changed on disk

A 'patch_template' call passed a base hash that no longer matches the template file on disk, so another writer changed the file since it was read. The patch is refused before anything is written, so a concurrent edit is never silently overwritten.

**Typical fix:** Re-inspect the template to get its current content hash, rebase the edit on the current file, and retry the patch.

# ARC-EDT-002 — Transaction write failed and was rolled back

Atomically replacing a project file failed partway through a transaction — disk full, a permissions error, or the file held open by another program. Every file the transaction had already replaced was restored from its backup, so the project matches its state before the edit.

**Typical fix:** Check disk space and file permissions, close programs holding project files open, then retry the edit.

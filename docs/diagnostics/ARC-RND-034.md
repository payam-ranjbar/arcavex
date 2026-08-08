# ARC-RND-034 — Font store could not be read or written

The font directory under the Arcavex home could not be read, created, or modified — typically a permissions problem, or a file held open by another process.

**Typical fix:** Check that the Arcavex home is readable and writable; 'arcavex doctor' reports which home directory is in effect.

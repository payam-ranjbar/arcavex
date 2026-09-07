# ARC-PRJ-014 — Unsafe project working path

An engine-managed .arcavex, pending queue, or proposal record path is a symlink, directory junction, or resolves outside the canonical project root. The operation is refused before following the path.

**Typical fix:** Replace linked working-state components with real directories and files contained by the canonical project root.

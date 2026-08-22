"""Semantic editing: the services that execute the contracts in ``kernel.editor``.

The kernel defines what a mutation *is*; this package is what makes one safe to run against a
project that other processes are also reading and writing. Three concerns, three modules:

- :mod:`locking` — one writer at a time, across processes, with a refusal a user can read.
- :mod:`transaction` — stage every write, validate the whole staged state, then replace atomically
  with rollback, so a rejected mutation leaves the project byte-identical.
- :mod:`history` — a bounded undo/redo log that stops at an edit it did not make rather than
  replaying over someone else's work.
"""

from __future__ import annotations

from arcavex.services.editor.locking import editor_lock

__all__ = ["editor_lock"]

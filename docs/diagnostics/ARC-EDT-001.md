# ARC-EDT-001 — Project is locked by another writer

A semantic edit could not acquire the project mutation lock: another Arcavex process — the desktop, an MCP client, or a CLI command — is writing to this project and did not release the lock within the wait. Nothing was changed.

**Typical fix:** Wait for the other process to finish and retry. If nothing is running, remove the stale .arcavex/project.lock file.

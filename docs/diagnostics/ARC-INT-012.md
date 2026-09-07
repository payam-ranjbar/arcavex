# ARC-INT-012 — Executable artifact could not be hashed

The running frozen executable was identified, but its bytes could not be read to compute the artifact SHA-256. The handshake retains the path and leaves the hash null rather than reporting unverified identity.

**Typical fix:** Ensure the executable still exists and is readable, then retry. Reinstall the Arcavex sidecar if the artifact was moved, replaced, or damaged.

# ARC-INT-010 — Build commit unavailable

The runtime has no explicit source-commit metadata, so the engine cannot prove which commit produced it. The handshake leaves build_commit null instead of guessing from a development checkout or inventing an identifier.

**Typical fix:** For a release, provide ARCAVEX_BUILD_COMMIT from the trusted build pipeline. In an interpreted development run, no action is required.

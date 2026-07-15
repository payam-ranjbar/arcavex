# ARC-RUN-002 — Recorded input changed on disk

A rerun on the same engine and platform did not reproduce the original bytes because a recorded input changed on disk since the run was recorded — the template, the project override patch, the style pack, a referenced asset, or the bundled font environment. The rerun renders from the current on-disk inputs and names which one drifted, rather than only reporting that the outputs differ. This is a warning: the render still succeeds.

**Typical fix:** Restore the named input to its recorded state to reproduce the original bytes, or accept the new render as the current truth. The run's reproduction.json lists the drifted inputs under 'input_drift'.

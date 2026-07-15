# ARC-EXT-051 — Golden output mismatch

An effect's rendered output differs from its stored golden image beyond the allowed tolerance.

**Typical fix:** Inspect the render; if the change is intended, regenerate the golden with GoldenHarness.save and review the image diff.

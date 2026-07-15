# ARC-EXT-051 — Golden output mismatch

An effect's rendered output differs from its stored golden image beyond the allowed tolerance.

**Typical fix:** Inspect the render; if the change is intended, regenerate the committed golden with 'python golden_test.py --update' and review the image diff.

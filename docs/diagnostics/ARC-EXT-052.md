# ARC-EXT-052 — Extension golden test failed

The extension's golden_test.py exited non-zero, timed out, or is missing, so the crash-contained golden run did not pass.

**Typical fix:** Run the test directly to see the failing check; the scaffold ships a golden_test.py that drives a GoldenHarness and exits non-zero on failure.

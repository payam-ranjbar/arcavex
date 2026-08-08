# ARC-EXT-053 — Extension test harness could not read test output

'ext test' could not start the golden_test.py subprocess, or could not read what it wrote. This is an Arcavex-side failure, so the extension's own result is unknown — it is reported apart from ARC-EXT-052, which says the extension's test really did fail.

**Typical fix:** Re-run 'arcavex ext test'. If it persists, check the extension directory is readable and that the interpreter running Arcavex can start a subprocess.

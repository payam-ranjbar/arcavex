PY := .venv/Scripts/python.exe
LINT_IMPORTS := .venv/Scripts/lint-imports.exe

# Every target below shells out to a tool that prints non-ASCII. Without this, the console
# codepage on Windows — the declared reference platform — silently truncates or kills that
# output: `contracts` printed *nothing* and exited 0, which is indistinguishable from a pass,
# so a broken contract set would have looked green to both CI and the developer.
export PYTHONIOENCODING := utf-8
export PYTHONUTF8 := 1

.PHONY: test lint typecheck contracts golden-update docs-diagnostics bench verify

test:
	$(PY) -m pytest tests -q

lint:
	$(PY) -m ruff check src tests

typecheck:
	$(PY) -m mypy src/arcavex/kernel --strict

# Must be the console script, not `$(PY) -m importlinter.cli lint`. That module form dispatches
# nothing: it exits 0 with no output even when a contract is deliberately broken (verified by
# adding a forbidden clients->kernel contract — the module form still passed), so this gate has
# been reporting green without checking anything. tests/unit/test_toolchain.py guards it.
contracts:
	$(LINT_IMPORTS)

# Regenerate the per-platform golden images, then review the diff before committing.
golden-update:
	ARCAVEX_UPDATE_GOLDENS=1 $(PY) -m pytest tests/golden -q

# Regenerate docs/diagnostics/*.md from the canonical catalog (services.diagnostics_catalog).
# newline='\n' is required: without it write_text() translates to CRLF on Windows, rewriting
# every committed (LF) file and burying a real change in a whole-directory diff. The mirror test
# reads back through universal newlines, so it cannot catch that on its own.
docs-diagnostics:
	$(PY) -c "from pathlib import Path; from arcavex.services.diagnostics_catalog import CATALOG, render_markdown; [ (Path('docs/diagnostics')/f'{c}.md').write_text(render_markdown(d), encoding='utf-8', newline='\n') for c,d in CATALOG.items() ]"

# Measure performance against the spec §8.2 targets and print the actuals.
bench:
	$(PY) scripts/benchmark.py

# The full release gate: lint, strict typecheck, architecture contracts, and the whole suite.
verify: lint typecheck contracts test

PY := .venv/Scripts/python.exe
LINT_IMPORTS := .venv/Scripts/lint-imports.exe

# The tools below print non-ASCII (box-drawing banners, arrows). Without these the Windows
# console codepage truncates that output: lint-imports emitted 552 bytes instead of 1188.
export PYTHONIOENCODING := utf-8
export PYTHONUTF8 := 1

.PHONY: test lint typecheck contracts golden-update docs-diagnostics bench verify

test:
	$(PY) -m pytest tests -q

lint:
	$(PY) -m ruff check src tests

typecheck:
	$(PY) -m mypy src/arcavex/kernel --strict

# Must be the console script. `$(PY) -m importlinter.cli lint` dispatches nothing: it exits 0
# with no output even against a deliberately broken contract. tests/unit/test_toolchain.py
# fails if that form returns here.
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

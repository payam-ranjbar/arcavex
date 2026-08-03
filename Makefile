PY := .venv/Scripts/python.exe

.PHONY: test lint typecheck contracts golden-update docs-diagnostics bench verify

test:
	$(PY) -m pytest tests -q

lint:
	$(PY) -m ruff check src tests

typecheck:
	$(PY) -m mypy src/arcavex/kernel --strict

contracts:
	$(PY) -m importlinter.cli lint

# Regenerate the per-platform golden images, then review the diff before committing.
golden-update:
	ARCAVEX_UPDATE_GOLDENS=1 $(PY) -m pytest tests/golden -q

# Regenerate docs/diagnostics/*.md from the canonical catalog (services.diagnostics_catalog).
# newline='\n' is required: Path.write_text defaults to os.linesep translation, so on Windows
# (the declared reference platform) this target otherwise rewrites all ~118 files with CRLF and
# reports the whole catalog as changed even when only one entry was edited.
docs-diagnostics:
	$(PY) -c "from pathlib import Path; from arcavex.services.diagnostics_catalog import CATALOG, render_markdown; [ (Path('docs/diagnostics')/f'{c}.md').open('w', encoding='utf-8', newline='\n').write(render_markdown(d)) for c,d in CATALOG.items() ]"

# Measure performance against the spec §8.2 targets and print the actuals.
bench:
	$(PY) scripts/benchmark.py

# The full release gate: lint, strict typecheck, architecture contracts, and the whole suite.
verify: lint typecheck contracts test

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
docs-diagnostics:
	$(PY) -c "from pathlib import Path; from arcavex.services.diagnostics_catalog import CATALOG, render_markdown; [ (Path('docs/diagnostics')/f'{c}.md').write_text(render_markdown(d), encoding='utf-8') for c,d in CATALOG.items() ]"

# Measure performance against the spec §8.2 targets and print the actuals.
bench:
	$(PY) scripts/benchmark.py

# The full release gate: lint, strict typecheck, architecture contracts, and the whole suite.
verify: lint typecheck contracts test

PY := .venv/Scripts/python.exe

.PHONY: test lint typecheck contracts

test:
	$(PY) -m pytest tests -q

lint:
	$(PY) -m ruff check src tests

typecheck:
	$(PY) -m mypy src/arcavex/kernel --strict

contracts:
	$(PY) -m importlinter.cli lint

"""Shared test fixtures and path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELLO_DIR = REPO_ROOT / "examples" / "hello-poster"
HELLO_TEMPLATE = HELLO_DIR / "template.yaml"
HELLO_DATA = HELLO_DIR / "data.yaml"


@pytest.fixture()
def hello_template() -> Path:
    """Path to the hello-poster template."""
    return HELLO_TEMPLATE


@pytest.fixture()
def hello_data() -> Path:
    """Path to the hello-poster data."""
    return HELLO_DATA


@pytest.fixture()
def arcavex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate ``$ARCAVEX_HOME`` (library, assets, cache) under a temp dir for a test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ARCAVEX_HOME", str(home))
    return home

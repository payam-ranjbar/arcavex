"""Doctor tests: report shape, probe rows, and engine version."""

from __future__ import annotations

from pathlib import Path

from arcavex.bootstrap import build_facade
from arcavex.services.doctor import run_doctor


def test_doctor_report_shape() -> None:
    facade = build_facade()
    report = facade.doctor()
    assert report.response_version == 1
    assert report.engine_version
    names = {c.name for c in report.checks}
    assert names == {
        "python", "skia", "icu", "fonts", "exporters", "cache", "temp_dir", "paths", "config"
    }
    for check in report.checks:
        assert check.status in {"ok", "warn", "fail"}
        assert check.detail


def test_doctor_ok_when_no_failures() -> None:
    report = run_doctor()
    # In a healthy dev environment every probe should pass.
    assert report.ok
    assert all(c.status != "fail" for c in report.checks)


def test_doctor_fonts_probe_lists_families() -> None:
    report = run_doctor()
    fonts = next(c for c in report.checks if c.name == "fonts")
    assert fonts.status == "ok"
    assert "Inter" in fonts.detail


def test_doctor_paths_and_cache_agree_on_home(monkeypatch) -> None:
    """DX-1: the 'paths' and 'cache' checks must report the same home root under one config.

    Both now resolve through ``fsutil.home_dir()``; previously ``paths`` hand-rolled an OS-temp
    default while ``cache`` followed ``home_dir()``, so a single ``doctor`` run reported two
    contradictory home directories.
    """
    monkeypatch.delenv("ARCAVEX_HOME", raising=False)
    report = run_doctor()
    paths = next(c for c in report.checks if c.name == "paths")
    cache = next(c for c in report.checks if c.name == "cache")
    home = str(Path.home() / ".arcavex")
    assert home in paths.detail
    assert home in cache.detail


def test_doctor_paths_follows_arcavex_home(monkeypatch, tmp_path) -> None:
    """With ARCAVEX_HOME set, 'paths' reports that home, not an OS-temp default."""
    monkeypatch.setenv("ARCAVEX_HOME", str(tmp_path))
    report = run_doctor()
    paths = next(c for c in report.checks if c.name == "paths")
    assert str(tmp_path) in paths.detail
    assert "env ARCAVEX_HOME" in paths.detail


def test_doctor_json_serializable() -> None:
    report = build_facade().doctor()
    payload = report.model_dump(mode="json")
    assert payload["response_version"] == 1
    assert isinstance(payload["checks"], list)

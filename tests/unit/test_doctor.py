"""Doctor tests: report shape, probe rows, and engine version."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def _packaged_icu() -> Path | None:
    """The `icudtl.dat` skia-python ships beside its module, if this build ships one.

    Only the Windows wheels do. Where there is no packaged copy there is nothing for Skia's loader
    to miss and nothing for doctor to explain, so the behaviour under test does not exist.
    """
    import skia

    packaged = Path(skia.__file__).resolve().parent / "icudtl.dat"
    return packaged if packaged.is_file() else None


def test_icu_row_explains_skias_stderr_line_when_the_data_file_is_not_beside_python(
    monkeypatch, tmp_path
) -> None:
    """A fresh install renders correctly and still prints "SkIcuLoader: datafile missing".

    Skia's loader probes next to the base interpreter, does not find the file there, says so on
    stderr, and then uses the copy inside skia-python. Shaping is fine, but the line lands above
    doctor's own all-ok table and at the start of every MCP session, so doctor names it rather
    than leaving a person to read it as a failure. Reproduced by pointing ``sys.base_prefix`` at
    an empty directory, which is what a newly downloaded managed Python looks like.
    """
    if _packaged_icu() is None:
        pytest.skip("this skia-python build ships no icudtl.dat, so the loader never misses one")
    monkeypatch.setattr("arcavex.services.doctor.sys.base_prefix", str(tmp_path))

    report = build_facade().doctor()
    icu = next(check for check in report.checks if check.name == "icu")

    assert icu.status == "ok", icu.detail
    assert "SkIcuLoader" in icu.detail
    assert str(tmp_path) in icu.detail
    assert icu.hint is not None and "icudtl.dat" in icu.hint


def test_icu_row_stays_plain_when_the_data_file_is_where_skia_looks(monkeypatch, tmp_path) -> None:
    (tmp_path / "icudtl.dat").write_bytes(b"not really ICU, but present")
    monkeypatch.setattr("arcavex.services.doctor.sys.base_prefix", str(tmp_path))

    icu = next(c for c in build_facade().doctor().checks if c.name == "icu")

    assert icu.status == "ok"
    assert "SkIcuLoader" not in icu.detail
    assert icu.hint is None

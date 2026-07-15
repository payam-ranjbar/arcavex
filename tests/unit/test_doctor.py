"""Doctor tests: report shape, probe rows, and engine version."""

from __future__ import annotations

from arcavex.bootstrap import build_facade
from arcavex.services.doctor import run_doctor


def test_doctor_report_shape() -> None:
    facade = build_facade()
    report = facade.doctor()
    assert report.response_version == 1
    assert report.engine_version
    names = {c.name for c in report.checks}
    assert names == {"python", "skia", "icu", "fonts", "temp_dir", "paths", "config"}
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


def test_doctor_json_serializable() -> None:
    report = build_facade().doctor()
    payload = report.model_dump(mode="json")
    assert payload["response_version"] == 1
    assert isinstance(payload["checks"], list)

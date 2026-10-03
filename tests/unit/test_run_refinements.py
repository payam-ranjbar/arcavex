"""Platform-independent naming, scoped homes, and installed skill identity."""

from __future__ import annotations

import runpy
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from arcavex.build_info import engine_label
from arcavex.services.fsutil import home_dir
from arcavex.services.skills import SKILL_NAME, SkillService
from arcavex.services.text import service


def _table(records: list[tuple[int, str]]) -> bytes:
    strings = b""
    entries = b""
    for name_id, name in records:
        encoded = name.encode("utf-16-be")
        entries += struct.pack(">HHHHHH", 3, 1, 0x409, name_id, len(encoded), len(strings))
        strings += encoded
    return struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + entries + strings


def test_font_family_is_independent_of_platform_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    face = SimpleNamespace(
        getFamilyName=lambda: "Archivo",  # simulated Windows backend truncation
        getTableData=lambda _: _table([(1, "Archivo"), (16, "Archivo Black")]),
    )
    monkeypatch.setattr(
        service, "skia", SimpleNamespace(Typeface=SimpleNamespace(MakeFromFile=lambda _: face))
    )
    assert service.read_font(Path("anything.ttf")) == (face, "Archivo Black")


def test_missing_name_table_falls_back_to_family_record() -> None:
    assert service._name_table_family(_table([(1, "Inter")])) == "Inter"
    assert service._name_table_family(b"invalid") is None
    assert service._name_table_family(b"") is None


def test_home_discovery_from_child_and_env_precedence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCAVEX_HOME", raising=False)
    local = tmp_path / ".arcavex-home"
    local.mkdir()
    child = tmp_path / "assets"
    child.mkdir()
    monkeypatch.chdir(child)
    assert home_dir() == local
    explicit = tmp_path / "other"
    monkeypatch.setenv("ARCAVEX_HOME", str(explicit))
    assert home_dir() == explicit


def test_home_does_not_cross_project_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCAVEX_HOME", raising=False)
    (tmp_path / ".arcavex-home").mkdir()
    project = tmp_path / "nested"
    project.mkdir()
    (project / "project.yaml").write_text("name: nested\n")
    monkeypatch.chdir(project)
    assert home_dir() == Path.home() / ".arcavex"


def test_skill_install_stamps_running_build(tmp_path: Path) -> None:
    report = SkillService().install(path=tmp_path)
    assert report.ok
    assert f"Engine build: `{engine_label()}`." in (tmp_path / SKILL_NAME / "SKILL.md").read_text()


def test_generated_reference_matches_live_cli() -> None:
    root = Path(__file__).resolve().parents[2]
    script = runpy.run_path(str(root / "scripts/generate_skill_reference.py"))
    reference = script["render_reference"]()
    assert script["OUTPUT"].read_text(encoding="utf-8") == reference
    for command in (
        "font add",
        "font list",
        "template new",
        "template patch",
        "layout inspect",
        "render",
        "batch",
        "doctor",
        "editor apply",
    ):
        assert f"`arcavex {command}`" in reference
    assert "--project" in reference and "--json" in reference


def test_source_distribution_payload_preserves_captured_commit(tmp_path: Path) -> None:
    import json

    root = Path(__file__).resolve().parents[2]
    stage = runpy.run_path(str(root / "packaging/payload.py"))["stage_payload"]
    source = tmp_path / "sdist"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    (source / "build-identity.json").write_text(json.dumps({"commit": "captured-release"}))
    skill = source / "skills" / SKILL_NAME
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("<!-- engine-build -->")
    payload = stage(source, tmp_path / "payload")
    assert json.loads((payload / "build.json").read_text())["commit"] == "captured-release"
    assert "captured-release" in (payload / "skill/SKILL.md").read_text()

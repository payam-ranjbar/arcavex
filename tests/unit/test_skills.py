"""Bundled-skill installation."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.services.skills import SKILL_NAME, SkillService, bundled_skill_dir


def test_repo_ships_the_skill() -> None:
    """A source checkout resolves the skill, so `skill install` works before any wheel build."""
    source = bundled_skill_dir()
    assert source is not None
    assert (source / "SKILL.md").is_file()
    assert (source / "references").is_dir()


def test_skill_frontmatter_is_present() -> None:
    """Harnesses key on the YAML frontmatter; without it the skill never triggers."""
    source = bundled_skill_dir()
    assert source is not None
    text = (source / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    head = text.split("---", 2)[1]
    assert f"name: {SKILL_NAME}" in head
    assert "description:" in head


def test_every_reference_link_resolves() -> None:
    """A dead reference link sends the agent looking for a file that is not there."""
    source = bundled_skill_dir()
    assert source is not None
    text = (source / "SKILL.md").read_text(encoding="utf-8")
    import re

    missing = [
        target
        for target in re.findall(r"\]\((references/[^)]+)\)", text)
        if not (source / target).is_file()
    ]
    assert not missing, f"SKILL.md links to missing files: {missing}"


def test_install_writes_the_tree(tmp_path: Path) -> None:
    report = SkillService().install(path=tmp_path)
    assert report.ok, report.diagnostics
    assert report.installed == [str(tmp_path / SKILL_NAME)]
    assert (tmp_path / SKILL_NAME / "SKILL.md").is_file()
    assert (tmp_path / SKILL_NAME / "references" / "extending.md").is_file()


def test_reinstall_without_force_is_refused(tmp_path: Path) -> None:
    """A user may have edited the installed copy; overwriting silently would discard that."""
    service = SkillService()
    assert service.install(path=tmp_path).ok
    second = service.install(path=tmp_path)
    assert second.installed == []
    assert any(d.code == "ARC-SKL-003" for d in second.diagnostics)


def test_force_overwrites(tmp_path: Path) -> None:
    service = SkillService()
    service.install(path=tmp_path)
    marker = tmp_path / SKILL_NAME / "SKILL.md"
    marker.write_text("edited", encoding="utf-8")
    report = service.install(path=tmp_path, force=True)
    assert report.ok
    assert marker.read_text(encoding="utf-8") != "edited"


def test_unknown_target_is_named(tmp_path: Path) -> None:
    report = SkillService().install(targets=["emacs"])
    assert not report.ok
    diag = report.diagnostics[0]
    assert diag.code == "ARC-SKL-001"
    assert "emacs" in diag.message
    assert diag.hint is not None and "claude-code" in diag.hint


def test_list_targets_writes_nothing(tmp_path: Path) -> None:
    report = SkillService().list_targets(tmp_path)
    assert report.ok
    assert report.installed == []
    assert not (tmp_path / SKILL_NAME).exists()


def test_presets_are_marked_verified_or_not() -> None:
    """The Claude Code layout is tested here; the others are the vendor's to move."""
    targets = {t.key: t for t in SkillService().list_targets().targets}
    assert targets["claude-code"].verified is True
    assert targets["codex"].verified is False
    assert targets["chatgpt"].verified is False


def test_targets_are_not_under_arcavex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A harness reads skills from its own config dir, not from ARCAVEX_HOME."""
    monkeypatch.setenv("ARCAVEX_HOME", str(tmp_path / "engine-home"))
    paths = [t.path for t in SkillService().list_targets().targets]
    assert all(str(tmp_path) not in p for p in paths), paths


def test_facade_exposes_install(tmp_path: Path) -> None:
    """The CLI reaches this through kernel.api, so the facade must carry it end to end."""
    report = build_facade().install_skill(path=tmp_path)
    assert report.ok, report.diagnostics
    assert (tmp_path / SKILL_NAME / "SKILL.md").is_file()

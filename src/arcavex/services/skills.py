"""Install the bundled design skill into an AI harness's skill directory.

The engine ships a skill that teaches an agent how to use it: the authoring loop, how to establish
an art direction, how to treat each aspect ratio, and how to build an effect the built-ins do not
provide. Discoverability is the whole point — the capability already exists, and an agent that does
not know it exists will not reach for it.

Targets are a small preset table plus an explicit path. Only the layout of the *destination* varies;
the skill content is identical everywhere.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from arcavex.kernel.api import SkillInstallReport, SkillTargetInfo
from arcavex.kernel.diagnostics import Diagnostic, diagnostic

SKILL_NAME = "arcavex-design-studio"


@dataclass(frozen=True)
class _Target:
    key: str
    label: str
    #: Path relative to the user's home directory.
    relative: str
    verified: bool


# `claude-code` is the layout this project tests against. The others follow each tool's documented
# user-level configuration directory; they are marked unverified because that convention is the
# vendor's to change, and `--path` exists precisely so a moved directory is never a blocker.
_TARGETS: tuple[_Target, ...] = (
    _Target("claude-code", "Claude Code", ".claude/skills", True),
    _Target("codex", "Codex", ".codex/skills", False),
    _Target("chatgpt", "ChatGPT", ".chatgpt/skills", False),
)

_TARGETS_BY_KEY = {t.key: t for t in _TARGETS}


def bundled_skill_dir() -> Path | None:
    """Locate the skill shipped with this installation, or ``None`` if it is absent.

    Two layouts: ``arcavex/_bundled/skill`` inside an installed wheel (created by the build's
    force-include), and ``skills/<name>`` in a source checkout.
    """
    packaged = Path(__file__).resolve().parents[1] / "_bundled" / "skill"
    if (packaged / "SKILL.md").is_file():
        return packaged
    source = Path(__file__).resolve().parents[3] / "skills" / SKILL_NAME
    if (source / "SKILL.md").is_file():
        return source
    return None


def target_infos(explicit: Path | None = None) -> list[SkillTargetInfo]:
    """Describe every install destination and whether the skill is already present."""
    if explicit is not None:
        destination = Path(explicit).expanduser().resolve() / SKILL_NAME
        return [
            SkillTargetInfo(
                key="path",
                label="Explicit path",
                path=str(destination),
                installed=(destination / "SKILL.md").is_file(),
                verified=True,
            )
        ]
    out: list[SkillTargetInfo] = []
    for target in _TARGETS:
        # The user's real home, not ARCAVEX_HOME: a harness reads its skills from its own config
        # directory, which is independent of where the engine keeps fonts and extensions.
        destination = Path.home() / target.relative / SKILL_NAME
        out.append(
            SkillTargetInfo(
                key=target.key,
                label=target.label,
                path=str(destination),
                installed=(destination / "SKILL.md").is_file(),
                verified=target.verified,
            )
        )
    return out


class SkillService:
    """Copies the bundled skill into one or more harness skill directories."""

    def list_targets(self, path: Path | None = None) -> SkillInstallReport:
        """Report every destination without writing anything."""
        source = bundled_skill_dir()
        if source is None:
            return _missing_skill()
        return SkillInstallReport(
            ok=True,
            skill=SKILL_NAME,
            source=str(source),
            targets=target_infos(path),
            installed=[],
        )

    def install(
        self,
        *,
        targets: list[str] | None = None,
        path: Path | None = None,
        force: bool = False,
    ) -> SkillInstallReport:
        """Copy the skill to each requested target; never raises.

        With neither ``targets`` nor ``path``, installs to every preset destination — the common
        case is a user who wants their assistants to know about the engine, not one in particular.
        """
        source = bundled_skill_dir()
        if source is None:
            return _missing_skill()

        if path is not None:
            wanted = target_infos(path)
        else:
            keys = targets or [t.key for t in _TARGETS]
            unknown = [k for k in keys if k not in _TARGETS_BY_KEY]
            if unknown:
                known = ", ".join(sorted(_TARGETS_BY_KEY))
                return SkillInstallReport(
                    ok=False,
                    skill=SKILL_NAME,
                    source=str(source),
                    targets=[],
                    installed=[],
                    diagnostics=[
                        diagnostic(
                            "ARC-SKL-001",
                            f"Unknown skill target {unknown[0]!r}",
                            hint=f"Use one of: {known}; or --path DIR for any other location.",
                        )
                    ],
                )
            wanted = [t for t in target_infos() if t.key in keys]

        installed: list[str] = []
        diagnostics: list[Diagnostic] = []
        for target in wanted:
            destination = Path(target.path)
            if destination.exists() and not force:
                if (destination / "SKILL.md").is_file():
                    diagnostics.append(
                        diagnostic(
                            "ARC-SKL-003",
                            f"Skill already installed at {destination}",
                            severity="warning",
                            hint="Pass --force to overwrite it with this build's version.",
                        )
                    )
                    continue
            try:
                if destination.exists():
                    shutil.rmtree(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination)
                installed.append(str(destination))
            except OSError as exc:
                diagnostics.append(
                    diagnostic(
                        "ARC-SKL-002",
                        f"Could not write the skill to {destination}: {exc.strerror or exc}",
                        hint="Check the directory is writable, or pass --path to choose another.",
                    )
                )

        return SkillInstallReport(
            ok=bool(installed) or not diagnostics,
            skill=SKILL_NAME,
            source=str(source),
            targets=wanted,
            installed=installed,
            diagnostics=diagnostics,
        )


def _missing_skill() -> SkillInstallReport:
    return SkillInstallReport(
        ok=False,
        skill=SKILL_NAME,
        source="",
        targets=[],
        installed=[],
        diagnostics=[
            diagnostic(
                "ARC-SKL-004",
                "This installation ships no bundled skill",
                hint=(
                    "Reinstall from a wheel built with the skill included, or run from a source "
                    "checkout where skills/ is present."
                ),
            )
        ],
    )

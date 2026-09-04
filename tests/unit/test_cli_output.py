"""Human CLI output a person copies from: a path must arrive whole.

These drive the presentation helpers with a narrow Rich console, the way an 80-column terminal
does, and assert that a long path is never folded or elided mid-filename. The ``--json`` forms are
untouched by these helpers and are covered by the end-to-end CLI tests.
"""

from __future__ import annotations

import io

from rich.console import Console

from arcavex.clients.cli import _print_preview_line, _print_skill_report
from arcavex.kernel.api import PreviewResult, SkillInstallReport, SkillTargetInfo

_LONG_PREVIEW_PATH = (
    "C:\\Users\\somebody\\AppData\\Local\\Arcavex\\cache\\preview\\"
    "0123456789abcdef.square.fa.png"
)


def _narrow_console(width: int) -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, width=width, no_color=True, force_terminal=False), buffer


def test_preview_prints_the_path_first_whole_on_its_own_line() -> None:
    """In an 80-column terminal the path used to follow the timings and get soft-wrapped across
    two lines, so neither a person pasting it into a viewer nor an assistant reading it back got
    a usable path."""
    console, buffer = _narrow_console(60)
    assert len(_LONG_PREVIEW_PATH) > 60
    result = PreviewResult(
        ok=True, output_path=_LONG_PREVIEW_PATH, compile_ms=12.34, render_ms=56.78
    )
    _print_preview_line(console, result, quiet=False, watching=False)
    lines = buffer.getvalue().splitlines()
    assert lines[0] == _LONG_PREVIEW_PATH
    assert "compile=12.3ms" in lines[1] and "render=56.8ms" in lines[1]


def test_preview_watch_line_keeps_the_path_whole_and_names_the_change() -> None:
    console, buffer = _narrow_console(60)
    result = PreviewResult(
        ok=True,
        output_path=_LONG_PREVIEW_PATH,
        changed_file="C:\\Users\\somebody\\poster\\data.yaml",
        compile_ms=1.0,
        render_ms=2.0,
    )
    _print_preview_line(console, result, quiet=False, watching=True)
    lines = buffer.getvalue().splitlines()
    assert lines[0] == _LONG_PREVIEW_PATH
    assert lines[1].startswith("changed=C:\\Users\\somebody\\poster\\data.yaml")


def test_skill_list_prints_every_path_whole_in_a_narrow_terminal() -> None:
    """The Rich table elided the destination column to '…' in a terminal under about 108
    columns, and the destination is exactly what a person runs --list to read."""
    console, buffer = _narrow_console(60)
    long_path = "C:\\Users\\somebody with a long name\\.codex\\skills\\arcavex-poster-studio"
    assert len(long_path) > 60
    report = SkillInstallReport(
        ok=True,
        skill="arcavex-poster-studio",
        source="C:\\src\\arcavex\\skills\\arcavex-poster-studio",
        targets=[
            SkillTargetInfo(
                key="claude-code",
                label="Claude Code (user)",
                path=long_path,
                installed=False,
                verified=True,
            ),
            SkillTargetInfo(
                key="agents",
                label="Codex / ChatGPT (Agent Skills)",
                path=long_path + "-agents",
                installed=True,
                verified=False,
            ),
        ],
    )
    _print_skill_report(console, report, list_only=True)
    text = buffer.getvalue()
    assert "…" not in text
    stripped = [line.strip() for line in text.splitlines()]
    assert long_path in stripped
    assert long_path + "-agents" in stripped
    # Each target reads top to bottom: label, then the path, then the state.
    first = stripped.index("Claude Code (user)")
    assert stripped[first + 1] == long_path
    assert stripped[first + 2] == "not installed"
    second = stripped.index("Codex / ChatGPT (Agent Skills)")
    assert stripped[second + 1] == long_path + "-agents"
    assert stripped[second + 2] == "installed (path unverified)"

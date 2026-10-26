#!/usr/bin/env python
"""Fail unless a built ``arcavex`` exposes the same top-level commands as the source CLI.

A frozen executable is a separate artifact from the wheel and can silently drift: PyInstaller
may drop a submodule, or the freeze may run from a different commit than ``cli.py``. Comparing
the exe's ``--help`` surface to the live Typer app turns "the version claims commands this build
does not have" into a build failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def parse_help_commands(help_text: str) -> set[str]:
    """Top-level command names from ``arcavex --help`` (plain Click, else a Rich panel).

    Captured output is plain: Typer only emits the bordered Rich panel when stdout is a tty.
    The parser keys on the ``Commands:`` heading and Click's two-space entry indent, then falls
    back to the panel form so an interactive capture still parses.
    """
    lines = help_text.splitlines()
    names: set[str] = set()
    for index, line in enumerate(lines):
        if line.strip() != "Commands:":
            continue
        for entry in lines[index + 1:]:
            if not entry.strip():
                break
            # Click's write_dl indents entries two spaces; wrapped help is indented further.
            if entry.startswith("  ") and not entry.startswith("   "):
                names.add(entry[2:].split()[0])
        break
    if names:
        return names
    in_panel = False
    for line in lines:
        stripped = line.strip()
        # Rich draws rounded or square corners depending on the console; the 0.1.0 standalone,
        # captured on Windows, uses the square set.
        if stripped.startswith(("╭", "┌")) and "Commands" in stripped:
            in_panel = True
        elif in_panel and stripped.startswith(("╰", "└")):
            break
        elif in_panel and stripped.startswith("│"):
            # A data row starts the command name in the first padded column; a wrapped
            # description line leaves that column blank.
            body = stripped[1:]
            if len(body) >= 2 and body[0] == " " and body[1] != " ":
                names.add(body.split()[0])
    return names


def source_command_groups() -> set[str]:
    """The single source of truth: the top-level names of the live Typer app."""
    from typer.main import get_command

    from arcavex.clients.cli import app

    return set(get_command(app).commands or {})


def frozen_help(exe: Path) -> str:
    result = subprocess.run(
        [str(exe), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"{exe} --help failed ({result.returncode}):\n{result.stderr}")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path, help="Built arcavex executable to inspect.")
    exe = parser.parse_args(argv).exe.resolve()
    if not exe.is_file():
        print(f"executable not found: {exe}", file=sys.stderr)
        return 1
    expected = source_command_groups()
    actual = parse_help_commands(frozen_help(exe))
    if actual != expected:
        print(f"CLI surface mismatch for {exe}", file=sys.stderr)
        if expected - actual:
            print(f"  missing from build: {sorted(expected - actual)}", file=sys.stderr)
        if actual - expected:
            print(f"  not in source cli.py: {sorted(actual - expected)}", file=sys.stderr)
        return 1
    print(f"ok: built CLI matches source ({len(actual)} top-level commands)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

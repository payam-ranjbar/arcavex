"""The first commands a reader meets must run against files that exist.

The hello poster was deleted with four other examples in a licence clean-up, and the README kept
rendering it for months: the very first command in the project's front door failed with
``ARC-TPL-001 File not found`` for anyone who downloaded the repository. Nothing caught it, because
no test read the documents the way a newcomer does. These do.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcavex.clients.cli import app

REPO = Path(__file__).resolve().parents[2]
FRONT_DOOR = ("README.md", "docs/install.md", "docs/quick-start.md", "docs/cli.md")
_EXAMPLE_PATH = re.compile(r"examples/[A-Za-z0-9_./-]*[A-Za-z0-9]")

runner = CliRunner()


def _documented_example_paths() -> dict[str, set[str]]:
    """Every ``examples/...`` path each front-door document names."""
    return {
        doc: set(_EXAMPLE_PATH.findall((REPO / doc).read_text(encoding="utf-8")))
        for doc in FRONT_DOOR
    }


@pytest.mark.parametrize("doc", FRONT_DOOR)
def test_every_example_path_the_document_names_exists(doc: str) -> None:
    missing = sorted(p for p in _documented_example_paths()[doc] if not (REPO / p).exists())
    assert not missing, f"{doc} names example paths that do not exist: {missing}"


def test_the_readme_opening_command_renders(tmp_path: Path, arcavex_home: Path) -> None:
    """The README's first code block, run as written (with -o pointed at a temp file)."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```bash\n(arcavex render [^`]+?)\n```", readme)
    assert block, "the README no longer opens with an `arcavex render` command"
    # Shell line continuations are not arguments.
    args = [token for token in block.group(1).split() if token != "\\"][1:]
    args[args.index("-o") + 1] = str(tmp_path / "out.png")

    result = runner.invoke(app, args, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert (tmp_path / "out.png").stat().st_size > 0


def test_the_quick_start_inspect_output_matches_the_example() -> None:
    """The quick start quotes ``template inspect``; the contract it quotes must be the real one."""
    result = runner.invoke(
        app, ["template", "inspect", "examples/hello-poster/template.yaml"], catch_exceptions=False
    )
    quick_start = (REPO / "docs/quick-start.md").read_text(encoding="utf-8")

    assert result.exit_code == 0, result.output
    for line in ("title: string (required) Main headline", "formats: square, story"):
        assert line in result.output, result.output
        assert line in quick_start, f"quick start no longer quotes {line!r}"

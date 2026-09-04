"""The first commands a reader meets must run against files that exist, and do what the text says.

The hello poster was deleted with four other examples in a licence clean-up, and the README kept
rendering it for months: the very first command in the project's front door failed with
``ARC-TPL-001 File not found`` for anyone who downloaded the repository. The quick start then
rendered a format the example does not declare and quoted an inference the engine never made.
Nothing caught any of it, because no test read the documents the way a newcomer does. These do.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcavex.clients.cli import app

REPO = Path(__file__).resolve().parents[2]
FRONT_DOOR = ("README.md", "docs/install.md", "docs/quick-start.md", "docs/cli.md")
_EXAMPLE_PATH = re.compile(r"examples/[A-Za-z0-9_./-]*[A-Za-z0-9]")
_CONSOLE_BLOCK = re.compile(r"```console\n(.*?)\n```", re.DOTALL)
_CLAIM = re.compile(r"^(inferred: \S+|(?:ERROR|WARNING) ARC-[A-Z]+-\d+)", re.MULTILINE)

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


# ------------------------------------------------------------ the quick start, run as written


def _quick_start_sessions() -> list[tuple[str, list[str], str]]:
    """Every ``$`` command in the quick start, with the output the document shows under it.

    Returns (command line, argv, shown output). Shell continuations are joined; the ``$ cp`` lines
    the document uses to set up a step are kept so the runner can perform them.
    """
    text = (REPO / "docs/quick-start.md").read_text(encoding="utf-8")
    sessions: list[tuple[str, list[str], str]] = []
    for block in _CONSOLE_BLOCK.findall(text):
        lines = block.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.startswith("$ "):
                i += 1
                continue
            command = line[2:]
            while command.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                command = command.rstrip()[:-1] + " " + lines[i].strip()
            i += 1
            shown: list[str] = []
            while i < len(lines) and not lines[i].startswith("$ "):
                shown.append(lines[i])
                i += 1
            sessions.append((command, command.split(), "\n".join(shown)))
    return sessions


def _is_self_contained(argv: list[str]) -> bool:
    """A command the test can run: it names shipped files, or needs none."""
    if "…" in argv or any(token.startswith("~") for token in argv):
        return False
    if argv[:1] == ["cp"]:
        return True
    if argv[:1] != ["arcavex"]:
        return False
    if argv[1:2] in (["explain"], ["ext"]):
        return True
    return any(token.startswith("examples/") or token == "mydata.yaml" for token in argv)


def test_the_quick_start_commands_run_as_written(
    tmp_path: Path, arcavex_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every self-contained quick-start command runs, and fails exactly when the text says so.

    The document opens by promising that every command is real and its output is what it actually
    prints. This holds it to that: it copies the two examples the quick start renders into a scratch
    directory and runs each command there, in document order, so the document itself has to enable
    the extension the Future Archive poster needs before it renders it.
    """
    for example in ("hello-poster", "future-archive-poster"):
        shutil.copytree(REPO / "examples" / example, tmp_path / "examples" / example)
    monkeypatch.chdir(tmp_path)

    ran = 0
    for command, argv, shown in _quick_start_sessions():
        if not _is_self_contained(argv):
            continue
        if argv[0] == "cp":
            shutil.copy(tmp_path / argv[1], tmp_path / argv[2])
            continue
        result = runner.invoke(app, argv[1:])
        ran += 1
        if "ERROR" in shown:
            assert result.exit_code != 0, f"{command!r} was documented as failing but succeeded"
        else:
            assert result.exit_code == 0, f"{command!r} failed:\n{result.output}"
        # A warning the document does not show is a surprise for the reader, and vice versa.
        assert ("WARNING" in result.output) == ("WARNING" in shown), (
            f"{command!r}: the document shows {'a' if 'WARNING' in shown else 'no'} warning; "
            f"the engine printed:\n{result.output}"
        )
        # A documented `inferred:` line is a claim about the engine; a documented code too.
        for claim in _CLAIM.findall(shown):
            assert claim in result.output, (
                f"{command!r} no longer prints {claim!r}:\n{result.output}"
            )
    assert ran >= 10, f"only {ran} quick-start commands were runnable; the document changed shape"

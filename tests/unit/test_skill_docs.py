"""The bundled skills name only commands and options the running CLI implements.

An agent follows the skill literally: a command or flag the build lacks costs it a failed call,
then a round of `--help` probing. The check walks every `arcavex ...` invocation in fenced code
and every inline code span that starts with a top-level command (`rerun --check`), and resolves
it against the live Typer command tree, so a renamed command or dropped flag fails here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer import _click as click
from typer.core import TyperGroup, TyperOption
from typer.main import get_command

from arcavex.clients.cli import app

SKILLS = Path(__file__).resolve().parents[2] / "skills"

# `arcavex` as a word followed by an argument: not `arcavex.exe`, `.arcavex-home`,
# `arcavex-design-studio` or the MCP tool names (`arcavex_template_patch`).
_INVOCATION = re.compile(r"(?<![\w./\\-])arcavex(?=\s)")
_INLINE_SPAN = re.compile(r"`([^`\n]+)`")
_FENCE = re.compile(r"^\s*```")
# A documented stand-in for a command name: `COMMAND`, `<group>`.
_PLACEHOLDER = re.compile(r"[A-Z][A-Z0-9_]*|<[^>]+>")
# Shell syntax that ends one command's arguments.
_COMMAND_END = re.compile(r"\s(?:\||>|2>|;|&&|#)")


@dataclass(frozen=True)
class Mention:
    file: Path
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.file.relative_to(SKILLS.parent)}:{self.line}: {self.text}"


def _root() -> click.Command:
    return get_command(app)


def _top_level_names() -> set[str]:
    root = _root()
    assert isinstance(root, TyperGroup)
    return set(root.commands)


def _mentions(path: Path, top_level: set[str]) -> list[Mention]:
    found: list[Mention] = []
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            for match in _INVOCATION.finditer(line):
                found.append(Mention(path, number, _COMMAND_END.split(line[match.start():])[0]))
            continue
        for span in _INLINE_SPAN.findall(line):
            span = _COMMAND_END.split(span)[0].strip()
            words = span.split()
            if not words:
                continue
            if _INVOCATION.match(span) or words == ["arcavex"]:
                found.append(Mention(path, number, span))
            elif words[0] in top_level:
                found.append(Mention(path, number, f"arcavex {span}"))
    return found


def _options(command: click.Command) -> set[str]:
    names = {"--help"}
    for param in command.params:
        if isinstance(param, TyperOption):
            names.update(param.opts)
            names.update(param.secondary_opts)
    return names


def _problem(mention: Mention) -> str | None:
    """Return why the mention does not resolve, or None when it does."""
    command = _root()
    path = ["arcavex"]
    for word in mention.text.split()[1:]:
        if word.startswith("-") and len(word) > 1:
            flag = word.split("=", 1)[0]
            if flag not in _options(command):
                return f"`{' '.join(path)}` has no option {flag}"
            continue
        if isinstance(command, TyperGroup):
            if _PLACEHOLDER.fullmatch(word):
                return None  # `arcavex COMMAND --help`: nothing concrete left to resolve
            if word not in command.commands:
                return f"`{' '.join(path)}` has no subcommand {word!r}"
            command = command.commands[word]
            path.append(word)
        # Past the leaf, bare words are arguments and option values.
    return None


def _all_mentions() -> list[Mention]:
    top_level = _top_level_names()
    return [m for md in sorted(SKILLS.rglob("*.md")) for m in _mentions(md, top_level)]


def test_skills_mention_cli_commands() -> None:
    """Guards the guard: an extractor that finds nothing would pass every skill."""
    texts = {m.text.split(" --")[0] for m in _all_mentions()}
    assert {"arcavex template patch", "arcavex render", "arcavex layout inspect"} <= texts


def test_every_mentioned_command_and_option_exists() -> None:
    problems = [f"{m} -> {why}" for m in _all_mentions() if (why := _problem(m))]
    assert not problems, "Skill docs name commands the CLI lacks:\n" + "\n".join(problems)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("arcavex rerun --check", "has no option --check"),
        ("arcavex font lst --json", "has no subcommand 'lst'"),
        ("arcavex template patch T --set nodes.a.b --value 1 --json", None),
        ("arcavex render T -f square -o out.png --dpi=48", None),
    ],
)
def test_resolution_rejects_what_the_cli_rejects(text: str, expected: str | None) -> None:
    why = _problem(Mention(SKILLS / "x.md", 1, text))
    if expected is None:
        assert why is None
    else:
        assert why is not None and expected in why


def test_extraction_covers_fences_and_bare_inline_spans(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "Use `rerun --check` and `arcavex_template_patch` and `.arcavex-home`.\n"
        "```bash\n"
        "arcavex effects list | grep grain   # confirm\n"
        "cd .arcavex-home\n"
        "```\n",
        encoding="utf-8",
    )
    texts = [m.text for m in _mentions(doc, _top_level_names())]
    assert texts == ["arcavex rerun --check", "arcavex effects list"]

"""The bundled design skill must describe the engine it ships with.

The skill is documentation an assistant acts on: every tool name, command path, and diagnostic code
in it is something the assistant will type. A drift audit found it telling assistants to
``pip install arcavex`` (not on PyPI), to run ``project render`` (no such command), and to call the
editor tools by names the MCP server does not register. Nothing caught any of it, because the skill
is prose and the registries it should agree with are code. These tests read the prose and check it
against the code: the MCP tool catalog, the Typer command tree, the diagnostics catalog, and the
Agent Skills frontmatter rules.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer
from ruamel.yaml import YAML
from typer.testing import CliRunner

from arcavex.clients.cli import app
from arcavex.clients.mcp_server import _TOOL_METHODS
from arcavex.services.diagnostics_catalog import documented_codes
from arcavex.services.skills import SKILL_NAME, bundled_skill_dir

# Commands the skill documents ahead of the engine. An entry is consulted only when the command is
# missing, so the skill can describe a command a sibling branch is adding without this test failing
# until the two meet; once the command lands the entry is dead and can be deleted.
_DOCUMENTED_AHEAD_OF_THE_ENGINE: dict[tuple[str, ...], str] = {}

# Registered tools the skill need not mention. The unprefixed tools (project_snapshot, layer_tree,
# hit_test, the policy and proposal tools) serve Arcavex Desktop's live view, and this one prefixed
# tool is the desktop's proposal-approval variant of arcavex_editor_apply.
_NOT_AUTHORING_TOOLS = {"arcavex_editor_apply_authorized"}

# https://agentskills.io/specification — the only frontmatter keys the standard defines.
_AGENT_SKILLS_KEYS = {
    "name", "description", "license", "compatibility", "metadata", "allowed-tools"
}

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MCP_TOOL = re.compile(r"\barcavex_[a-z0-9_]+")
_DIAGNOSTIC_CODE = re.compile(r"\bARC-[A-Z]{3}-\d{3}\b")
_SUBCOMMAND_WORD = re.compile(r"[a-z][a-z0-9-]*")


def _skill_root() -> Path:
    root = bundled_skill_dir()
    assert root is not None, "this checkout ships no skill"
    return root


def _documents() -> list[Path]:
    root = _skill_root()
    return [root / "SKILL.md", *sorted((root / "references").glob("*.md"))]


def _fenced_blocks(text: str) -> list[str]:
    return _FENCE.findall(text)


def _inline_spans(text: str) -> list[str]:
    """Inline code spans, with fenced blocks removed first so their fences do not pair up."""
    return _INLINE_CODE.findall(_FENCE.sub("", text))


def _command_tree() -> dict[str, set[str] | None]:
    """Top-level command name -> its subcommands, or None for a leaf command, from the Typer app."""
    root = typer.main.get_command(app)
    tree: dict[str, set[str] | None] = {}
    for name, command in root.commands.items():
        # Typer vendors its own click, so isinstance(command, click.Group) is unreliable here; a
        # group is whatever carries subcommands.
        subcommands = getattr(command, "commands", None)
        tree[name] = None if subcommands is None else set(subcommands)
    return tree


def _command_paths(candidate: str, tree: dict[str, set[str] | None]) -> list[tuple[str, ...]]:
    """The command paths one backticked string names, or [] when it is not a CLI invocation.

    ``arcavex template inspect --json`` names ("template", "inspect"); ``validate --format F``
    names ("validate",); ``ext scaffold/validate/test`` names three paths. A string whose first
    word is not a top-level command — a file path, a YAML key, ``python -m arcavex``, an MCP tool —
    is prose, not a claim about the CLI, and is left alone.
    """
    words = candidate.split("#", 1)[0].replace("$", " ").split()
    if words and words[0] == "arcavex":
        words = words[1:]
    if not words or words[0] not in tree:
        return []
    head = words[0]
    if tree[head] is None or len(words) == 1:
        return [(head,)]  # a leaf command (whatever follows is arguments), or a group named alone
    if not _SUBCOMMAND_WORD.fullmatch(words[1].split("/")[0]):
        return [(head,)]  # the group followed by an option or a placeholder, not a subcommand
    return [(head, sub) for sub in words[1].split("/")]


def _named_commands() -> dict[tuple[str, ...], set[str]]:
    """Every command path the skill names, in inline code or as an ``arcavex`` line in a fence."""
    tree = _command_tree()
    named: dict[tuple[str, ...], set[str]] = {}
    for document in _documents():
        text = document.read_text(encoding="utf-8")
        candidates = _inline_spans(text) + [
            line
            for block in _fenced_blocks(text)
            for line in block.splitlines()
            if line.lstrip("$ ").startswith("arcavex ")
        ]
        for candidate in candidates:
            for path in _command_paths(candidate, tree):
                named.setdefault(path, set()).add(document.name)
    return named


# --------------------------------------------------------------------------- MCP tool names


def test_every_prefixed_tool_name_the_skill_uses_is_registered() -> None:
    """An ``arcavex_*`` name in the skill is a tool the assistant will call; it had better exist.

    Unprefixed names are not checked: ``layer_tree`` and ``project_snapshot`` are registered tools,
    but ``set_property`` and ``resolved_text`` are field names spelt the same way.
    """
    registered = {name for name, _ in _TOOL_METHODS}
    for document in _documents():
        named = set(_MCP_TOOL.findall(document.read_text(encoding="utf-8")))
        unknown = sorted(named - registered)
        assert not unknown, f"{document.name} names unregistered MCP tools: {unknown}"


def test_the_skill_names_every_authoring_tool() -> None:
    """A tool the skill never mentions is a tool an MCP-only assistant never learns exists.

    That is how an assistant restricted to MCP came to reconstruct the template grammar from
    validation failures: the tools were there, the skill did not say so.
    """
    text = "\n".join(d.read_text(encoding="utf-8") for d in _documents())
    authoring = {
        name for name, _ in _TOOL_METHODS if name.startswith("arcavex_")
    } - _NOT_AUTHORING_TOOLS
    missing = sorted(name for name in authoring if name not in text)
    assert not missing, f"registered MCP tools the skill never mentions: {missing}"


# --------------------------------------------------------------------------- CLI command paths


def test_the_extractor_reads_the_skills_commands() -> None:
    """If the extractor ever finds nothing, the command test below passes vacuously."""
    named = _named_commands()
    assert ("render",) in named and ("template", "inspect") in named, sorted(named)


def test_the_extractor_separates_commands_from_prose() -> None:
    """The phantom the audit found must register as a claim; ordinary code spans must not."""
    tree = _command_tree()
    assert _command_paths("project render", tree) == [("project", "render")]
    assert "render" not in (tree["project"] or set()), "the phantom exists now? update the skill"
    assert _command_paths("arcavex ext scaffold/validate/test", tree) == [
        ("ext", "scaffold"), ("ext", "validate"), ("ext", "test")
    ]
    assert _command_paths("$ arcavex render poster.yaml -o a.png  # hashes", tree) == [("render",)]
    for prose in ("python -m arcavex --version", "style: {align: center}", "arcavex_render",
                  "ARCAVEX_HOME", "--json", "start out.png"):
        assert _command_paths(prose, tree) == [], prose


def test_every_command_path_the_skill_names_exists() -> None:
    """Each backticked ``arcavex <cmd> [<sub>]`` must answer ``--help`` with exit code 0.

    Driven through Typer's runner rather than a subprocess: the test is about the command tree, not
    about PATH.
    """
    tree = _command_tree()
    runner = CliRunner()
    for path, documents in sorted(_named_commands().items()):
        if len(path) == 2 and path[1] not in (tree[path[0]] or set()):
            if path in _DOCUMENTED_AHEAD_OF_THE_ENGINE:
                continue
            raise AssertionError(
                f"{sorted(documents)} name `arcavex {' '.join(path)}`, which does not exist; "
                f"{path[0]} has: {sorted(tree[path[0]] or set())}"
            )
        result = runner.invoke(app, [*path, "--help"])
        assert result.exit_code == 0, (
            f"`arcavex {' '.join(path)} --help` (named in {sorted(documents)}) failed: "
            f"{result.output}"
        )


# --------------------------------------------------------------------------- diagnostic codes


def test_every_diagnostic_code_the_skill_cites_is_documented() -> None:
    """A cited code the catalog does not know sends the assistant to ``explain`` for nothing."""
    known = documented_codes()
    for document in _documents():
        cited = set(_DIAGNOSTIC_CODE.findall(document.read_text(encoding="utf-8")))
        unknown = sorted(cited - known)
        assert not unknown, f"{document.name} cites undocumented diagnostic codes: {unknown}"


# --------------------------------------------------------------------------- frontmatter


def test_frontmatter_follows_the_agent_skills_specification() -> None:
    """Hosts key on the frontmatter; a field outside the standard, or an over-long description,
    is what makes a skill silently fail to load or to trigger.
    """
    text = (_skill_root() / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    meta = YAML(typ="safe").load(text.split("---", 2)[1])
    assert isinstance(meta, dict)
    assert set(meta) <= _AGENT_SKILLS_KEYS, f"keys outside the Agent Skills standard: {set(meta)}"

    name = meta["name"]
    assert name == SKILL_NAME, "the installed directory is named after the skill; they must agree"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64, name

    description = meta["description"]
    assert isinstance(description, str)
    assert 0 < len(description) <= 1024, f"description is {len(description)} chars; the cap is 1024"

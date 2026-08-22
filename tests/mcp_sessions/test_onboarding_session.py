"""What an assistant can learn about Arcavex from Arcavex, over MCP alone.

A client that connects to this server arrives knowing nothing: not the template grammar, not the
shape of an edit, not that a design skill ships in the box. Everything it can discover has to come
from the catalog, the instructions, and the resources — there is no documentation channel besides.

Two AI agents were given the same design brief for this product. The one allowed to read files and
run the CLI scaffolded a template and was rendering in minutes. The one restricted to MCP spent 28
deliberate validation failures reconstructing the template grammar and 214 attempts reconstructing
the shape of an edit, because neither was reachable from here. These tests exist so that gap
cannot quietly reopen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.clients.mcp_server import _INSTRUCTIONS, _TOOL_METHODS, ArcavexTools, build_mcp_server


@pytest.fixture(scope="module")
def tools() -> ArcavexTools:
    return ArcavexTools(build_facade())


@pytest.fixture()
def isolated_tools(arcavex_home: Path) -> ArcavexTools:
    """Tools over a facade whose library lives in a temp home.

    Publishing writes into the shared library, so a test that used the default home would install
    a template into the developer's own ~/.arcavex and fail on its second run.
    """
    assert arcavex_home.is_dir()
    return ArcavexTools(build_facade())


# ------------------------------------------------------------------ the guide is reachable


@pytest.mark.anyio
async def test_the_design_guide_is_served_as_a_resource() -> None:
    """The skill that teaches an assistant this engine must be readable from the engine.

    `arcavex skill install` copies it into Claude Code's or Codex's skill directory, which helps
    exactly two hosts and only when a person runs it. Any other client — including the ones this
    server exists for — could not previously learn that the document exists at all.
    """
    server = build_mcp_server(build_facade())

    resources = await server.list_resources()
    uris = {str(resource.uri) for resource in resources}

    assert any(uri.endswith("SKILL.md") for uri in uris), f"no skill resource among {uris}"


@pytest.mark.anyio
async def test_the_guide_reads_back_with_its_content() -> None:
    server = build_mcp_server(build_facade())
    resources = await server.list_resources()
    skill = next(r for r in resources if str(r.uri).endswith("SKILL.md"))

    contents = await server.read_resource(skill.uri)
    body = "".join(part.content for part in contents if isinstance(part.content, str))

    assert "Arcavex" in body
    assert len(body) > 500, "the guide came back empty or truncated"


@pytest.mark.anyio
async def test_the_guides_own_references_are_reachable_too() -> None:
    """The skill points at reference documents; a pointer to nothing is worse than no pointer."""
    server = build_mcp_server(build_facade())

    uris = {str(resource.uri) for resource in await server.list_resources()}

    assert any("engine-and-loop" in uri for uri in uris), sorted(uris)


def test_the_instructions_say_where_the_guide_is() -> None:
    """A resource nobody is told about is a resource nobody reads."""
    assert "skill" in _INSTRUCTIONS.lower() or "guide" in _INSTRUCTIONS.lower()


def test_the_instructions_mention_editing() -> None:
    """The editor tools are the whole Phase 2 surface and went unmentioned."""
    assert "editor" in _INSTRUCTIONS.lower()


# ------------------------------------------------- a design can be started from nothing


def test_a_template_can_be_scaffolded_over_mcp(tools: ArcavexTools, tmp_path: Path) -> None:
    """Creating a design from zero must not require leaving the protocol.

    Without this an assistant's only route to a new template is to hand-write YAML with its own
    file tools and learn the grammar from refusals — which is precisely what happened.
    """
    report = tools.template_new(target=str(tmp_path / "seed"), name="seed")

    assert report.ok, report.diagnostics
    assert (tmp_path / "seed" / "template.yaml").is_file()


def test_a_scaffolded_template_validates_and_is_editable(
    tools: ArcavexTools, tmp_path: Path
) -> None:
    """The scaffold has to be a working starting point, not a stub that fails its own validator."""
    tools.template_new(target=str(tmp_path / "seed"), name="seed")

    checked = tools.template_validate(template=str(tmp_path / "seed"))

    assert checked.ok, [d.model_dump() for d in checked.diagnostics]


def test_a_template_can_be_published_over_mcp(
    isolated_tools: ArcavexTools, tmp_path: Path
) -> None:
    """Publishing is what makes project_create able to pin a name instead of a path."""
    isolated_tools.template_new(target=str(tmp_path / "seed"), name="seed")

    published = isolated_tools.template_publish(
        template=str(tmp_path / "seed"), name="seed-kit", version="1.0.0"
    )

    assert published.ok, [d.model_dump() for d in published.diagnostics]


def test_every_new_tool_is_registered_with_the_server() -> None:
    """A method nobody registered is a method no client can call."""
    registered = {method for _name, method in _TOOL_METHODS}

    for method in ("template_new", "template_publish"):
        assert method in registered, f"{method} exists but is not exposed"


def test_a_pinned_template_can_be_detached_over_mcp(
    isolated_tools: ArcavexTools, tmp_path: Path
) -> None:
    """The refusal for an outside template names detach, so detach has to be reachable from here.

    Pointing an assistant at a command it cannot run is the same as refusing with no way out.
    """
    isolated_tools.template_new(target=str(tmp_path / "seed"), name="seed")
    created = isolated_tools.project_create(
        target=str(tmp_path / "post"), template=str(tmp_path / "seed"), formats=["square"]
    )
    assert created.ok, [d.model_dump() for d in created.diagnostics]

    detached = isolated_tools.template_detach(project=str(tmp_path / "post"))

    assert detached.ok, [d.model_dump() for d in detached.diagnostics]
    # The point of detaching is that the template now lives inside the project, which is the one
    # condition semantic editing requires.
    copied = Path(detached.path or "")
    assert copied.is_dir() and (copied / "template.yaml").is_file()
    assert copied.resolve().is_relative_to((tmp_path / "post").resolve())

"""What an assistant's tool ARGUMENTS get back from the Arcavex MCP server.

A live audit gave a blind assistant (MCP only: no files, no CLI, no screen) a design brief. It lost
a round trip to every item pinned here. An unknown key was accepted and ignored, so it believed
``format`` on ``arcavex_template_new`` had taken effect. A missing key came back as raw pydantic
text, unlike every domain refusal. No parameter carried a description. ``project_preview`` returned
cache paths it could not open. One ``dpi`` applied to every format. A preview of an A2 poster was a
4000-pixel image on every call. Bundled fonts read ``installed: false``, which it took as
"unusable". And hints told it to pass ``--project``, a flag it has no way to pass.
"""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import Image
from mcp.types import CallToolResult, ImageContent, TextContent

from arcavex.clients.mcp_server import ArcavexTools, tool_catalog
from arcavex.kernel.api import PatchOp, PreviewProjectReport


def _call(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Drive the real FastMCP dispatch, one fresh event loop per call."""
    return asyncio.run(server.call_tool(name, arguments))


def _refusal(result: Any) -> dict[str, Any]:
    """Assert ``result`` is the coded argument refusal and return its envelope."""
    assert isinstance(result, CallToolResult), type(result)
    assert result.isError is True
    assert result.structuredContent is not None
    # The text block carries the same envelope, for a client that shows only text.
    text = next(block for block in result.content if isinstance(block, TextContent))
    assert json.loads(text.text) == result.structuredContent
    assert result.structuredContent["ok"] is False
    return result.structuredContent


def _png_size(path: Path) -> tuple[int, int]:
    """Read a PNG's pixel size from its IHDR chunk (no decoder needed)."""
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def _seed_project(tools: ArcavexTools, tmp_path: Path) -> Path:
    """A scaffolded template (square 1080x1080 and story 1080x1920, both @96dpi) in a project."""
    seed = tmp_path / "seed"
    assert tools.template_new(target=str(seed), name="seed").ok
    project = tmp_path / "post"
    created = tools.project_create(target=str(project), template=str(seed))
    assert created.ok, [d.model_dump() for d in created.diagnostics]
    return project


# ------------------------------------------------------------- unknown arguments are refused


def test_an_unknown_argument_is_refused_before_anything_runs(server: Any, tmp_path: Path) -> None:
    """``arcavex_template_new {format: square}`` returned ok:true; the assistant believed it.

    The generated argument model ignored unknown keys, so an option that does not exist looked
    exactly like one that took effect. The refusal has to come BEFORE dispatch: nothing may be
    scaffolded under a belief that will be wrong.
    """
    target = tmp_path / "seed"

    envelope = _refusal(
        _call(server, "arcavex_template_new", {"target": str(target), "format": "square"})
    )

    [diag] = envelope["diagnostics"]
    assert diag["code"] == "ARC-MCP-010"
    assert "format" in diag["message"] and "arcavex_template_new" in diag["message"]
    assert "target" in diag["hint"] and "name" in diag["hint"], diag["hint"]
    assert not target.exists(), "the tool ran despite the unknown argument"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("arcavex_template_new", {"target": "seed", "formats": ["square"]}),
        ("arcavex_project_create", {"target": "post", "template": "seed", "dpi": 300}),
        ("arcavex_render", {"template": "seed", "scale": 2}),
    ],
)
def test_every_silent_pass_from_the_audit_is_now_a_refusal(
    server: Any, tool: str, arguments: dict[str, Any]
) -> None:
    envelope = _refusal(_call(server, tool, arguments))

    assert [d["code"] for d in envelope["diagnostics"]] == ["ARC-MCP-010"]


def test_a_near_miss_key_suggests_the_field_that_exists(server: Any) -> None:
    """``formats`` on a tool whose field is ``format`` should point at ``format``."""
    envelope = _refusal(
        _call(server, "arcavex_render", {"template": "seed", "formats": ["square"]})
    )

    [diag] = envelope["diagnostics"]
    assert "'format'" in diag["hint"], diag["hint"]


# ------------------------------------------------- missing / mistyped arguments are coded too


def test_a_missing_required_argument_is_a_coded_diagnostic_not_validator_prose(
    server: Any,
) -> None:
    """The one place an assistant met "1 validation error for template_newArguments"."""
    envelope = _refusal(_call(server, "arcavex_template_new", {}))

    [diag] = envelope["diagnostics"]
    assert diag["code"] == "ARC-MCP-011"
    assert "target" in diag["message"] and "arcavex_template_new" in diag["message"]
    assert "validation error" not in json.dumps(envelope).lower()
    # The hint is the tool's argument guide: required fields, then optional, each with meaning.
    assert diag["hint"].startswith("Required: target ("), diag["hint"]
    assert "Optional: name (" in diag["hint"], diag["hint"]


def test_a_mistyped_argument_names_the_field_and_what_it_expects(server: Any) -> None:
    envelope = _refusal(_call(server, "arcavex_render", {"template": "seed", "dpi": "high"}))

    [diag] = envelope["diagnostics"]
    assert diag["code"] == "ARC-MCP-012"
    assert "'dpi'" in diag["message"] and "arcavex_render" in diag["message"]
    assert diag["source"]["keypath"] == "dpi"
    assert diag["hint"].startswith("dpi: "), diag["hint"]
    assert "integer" in diag["hint"]


def test_every_problem_in_a_call_is_reported_at_once(server: Any) -> None:
    """One round trip per defect was the audit's whole cost; do not ration the findings."""
    envelope = _refusal(
        _call(server, "arcavex_render", {"dpi": "high", "scale": 2})  # missing, bad, unknown
    )

    codes = sorted(d["code"] for d in envelope["diagnostics"])
    assert codes == ["ARC-MCP-010", "ARC-MCP-011", "ARC-MCP-012"]


def test_valid_calls_still_pass_straight_through(server: Any, tmp_path: Path) -> None:
    """The contract must cost a correct caller nothing, including Claude Desktop's habit of
    sending a list as its JSON text (``"[\\"square\\"]"``), which the SDK pre-parses."""
    seed = tmp_path / "seed"
    _content, scaffolded = _call(server, "arcavex_template_new", {"target": str(seed)})
    assert scaffolded["ok"] is True and (seed / "template.yaml").is_file()

    _content, created = _call(
        server,
        "arcavex_project_create",
        {"target": str(tmp_path / "post"), "template": str(seed), "formats": '["square"]'},
    )

    assert created["ok"] is True, created["diagnostics"]


# ---------------------------------------------------------------- the catalog documents itself


def test_every_parameter_of_every_tool_is_described_and_unknown_keys_are_declared_illegal(
    server: Any,
) -> None:
    """The inputSchema carried names and types only; ``additionalProperties`` was unset.

    A description per parameter is what lets an assistant pass the right thing first time;
    ``additionalProperties: false`` lets a well-behaved client refuse an unknown key locally.
    """
    for tool in tool_catalog(server):
        schema = tool["inputSchema"]
        assert schema.get("additionalProperties") is False, tool["name"]
        for name, prop in schema.get("properties", {}).items():
            assert prop.get("description"), f"{tool['name']}.{name} has no description"


def test_the_preview_dpi_descriptions_recommend_a_small_dpi_while_iterating(server: Any) -> None:
    catalog = {tool["name"]: tool for tool in tool_catalog(server)}

    dpi = catalog["arcavex_render_preview"]["inputSchema"]["properties"]["dpi"]["description"]

    assert "96" in dpi


# ------------------------------------------------------- project_preview shows the pictures


def test_project_preview_returns_the_pictures_and_keeps_the_viewer_contract(
    server: Any, tools: ArcavexTools, tmp_path: Path
) -> None:
    """``project_preview`` returned cache paths only; ``arcavex_render_preview`` returned the image.

    A blind assistant cannot open a path. It gets one image block per rendered target now, while
    Arcavex Desktop keeps what it reads: the structured report (also first in ``content``, which
    the sidecar reads as ``content[0].text``) validated by the unchanged output schema.
    """
    project = _seed_project(tools, tmp_path)

    result = _call(server, "project_preview", {"project": str(project), "dpi": 72})

    assert isinstance(result, CallToolResult) and result.isError is False
    report = PreviewProjectReport.model_validate(result.structuredContent)
    assert report.ok, [d.model_dump() for d in report.diagnostics]
    assert report.previews, "a scaffolded project declares targets"
    images = [block for block in result.content if isinstance(block, ImageContent)]
    assert len(images) == len(report.previews)
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text)["ok"] is True
    for preview in report.previews:
        assert preview.compile_ms is not None and preview.render_ms is not None
        assert preview.dpi == 72
        assert preview.width_px and preview.height_px
        assert _png_size(Path(preview.output_path or "")) == (preview.width_px, preview.height_px)


def test_project_preview_output_schema_is_still_the_report(server: Any) -> None:
    catalog = {tool["name"]: tool for tool in tool_catalog(server)}

    assert catalog["project_preview"]["outputSchema"] == PreviewProjectReport.model_json_schema()


# ---------------------------------------------------------------- per-format dpi on a render


def test_project_render_takes_a_dpi_per_format(tools: ArcavexTools, tmp_path: Path) -> None:
    """``{dpi: 300}`` rendered every format at 300; a social tile and an A2 poster share nothing."""
    project = _seed_project(tools, tmp_path)

    run = tools.project_render(project=str(project), dpi={"square": 48, "story": 24})

    assert run.ok, [d.model_dump() for d in run.diagnostics]
    sizes = {Path(path).name: _png_size(Path(path)) for path in run.outputs}
    # square: 1080px @96 = 810pt -> 540px @48; story: 810x1440pt -> 270x480 @24.
    assert sizes[next(n for n in sizes if ".square" in n)] == (540, 540)
    assert sizes[next(n for n in sizes if ".story" in n)] == (270, 480)
    manifest = json.loads((Path(run.run_dir or "") / "manifest.json").read_text("utf-8"))
    assert manifest["dpi"] == {"square": 48, "story": 24}
    recorded = {o["format"]: (o["width"], o["height"]) for o in manifest["outputs"]}
    assert recorded == {"square": (540, 540), "story": (270, 480)}


def test_a_per_format_dpi_run_reproduces_from_its_manifest(
    tools: ArcavexTools, tmp_path: Path
) -> None:
    project = _seed_project(tools, tmp_path)
    run = tools.project_render(project=str(project), dpi={"square": 48})
    assert run.ok, [d.model_dump() for d in run.diagnostics]

    reproduced = tools.run_rerun(run_dir=run.run_dir)

    assert reproduced.ok, [d.model_dump() for d in reproduced.diagnostics]


def test_a_single_dpi_still_applies_to_every_format(tools: ArcavexTools, tmp_path: Path) -> None:
    project = _seed_project(tools, tmp_path)

    run = tools.project_render(project=str(project), dpi=48)

    assert run.ok, [d.model_dump() for d in run.diagnostics]
    sizes = sorted(_png_size(Path(path)) for path in run.outputs)
    assert sizes == [(540, 540), (540, 960)]


def test_a_dpi_for_an_undeclared_format_is_refused_naming_the_declared_ones(
    tools: ArcavexTools, tmp_path: Path
) -> None:
    project = _seed_project(tools, tmp_path)

    run = tools.project_render(project=str(project), dpi={"a2": 300})

    assert run.ok is False
    [diag] = run.diagnostics
    assert diag.code == "ARC-TPL-022" and "a2" in diag.message
    assert "square" in (diag.hint or "") and "story" in (diag.hint or "")


# ------------------------------------------------------------- a preview bounded in pixels


def test_render_preview_max_px_bounds_the_longest_side(tools: ArcavexTools, tmp_path: Path) -> None:
    """Iterating on a poster must not cost a 4000-pixel image per call."""
    seed = tmp_path / "seed"
    assert tools.template_new(target=str(seed), name="seed").ok

    blocks = tools.render_preview(template=str(seed), format="story", max_px=480)

    image = next(block for block in blocks if isinstance(block, Image))
    text = next(block for block in blocks if isinstance(block, TextContent))
    result = json.loads(text.text)
    assert result["ok"], result["diagnostics"]
    width, height = _png_size(Path(image.path or ""))
    assert (width, height) == (270, 480)
    # The JSON block tells the truth about what was rendered, not what was declared.
    assert (result["dpi"], result["width_px"], result["height_px"]) == (24, 270, 480)


def test_render_preview_max_px_never_upscales(tools: ArcavexTools, tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    assert tools.template_new(target=str(seed), name="seed").ok

    blocks = tools.render_preview(template=str(seed), format="square", max_px=5000)

    result = json.loads(next(b for b in blocks if isinstance(b, TextContent)).text)
    assert (result["dpi"], result["width_px"], result["height_px"]) == (96, 1080, 1080)


def test_render_preview_without_a_bound_reports_the_declared_dpi(
    tools: ArcavexTools, tmp_path: Path
) -> None:
    seed = tmp_path / "seed"
    assert tools.template_new(target=str(seed), name="seed").ok

    blocks = tools.render_preview(template=str(seed), format="square")

    result = json.loads(next(b for b in blocks if isinstance(b, TextContent)).text)
    assert (result["dpi"], result["width_px"], result["height_px"]) == (96, 1080, 1080)


# --------------------------------------------------------------- fonts read as usable


def test_font_list_marks_every_resolvable_family_available(tools: ArcavexTools) -> None:
    """Bundled families reported ``installed: false`` with paths inside the developer checkout,
    which an assistant read as "not usable". ``available`` answers the question it was asking."""
    report = tools.font_list()

    assert report.ok and report.families
    for family in report.families:
        assert family.available is True, family
        expected = (
            "bundled+installed"
            if family.bundled and family.installed
            else "installed"
            if family.installed
            else "bundled"
        )
        assert family.source == expected, family


# ------------------------------------------------------------- hints that reach an MCP caller


def test_no_project_hints_name_the_argument_and_the_tool_an_mcp_caller_has(
    tools: ArcavexTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"pass --project <dir>, or create one with arcavex project new" to a caller whose field is
    ``project`` and whose tool is ``arcavex_project_create``."""
    monkeypatch.chdir(tmp_path)

    nowhere = tools.project_status(project=str(tmp_path / "nowhere"))
    walked = tools.project_status()

    for report in (nowhere, walked):
        [diag] = [d for d in report.diagnostics if d.code == "ARC-PRJ-001"]
        assert "--project" in (diag.hint or "") and "'project'" in (diag.hint or ""), diag.hint
    assert "arcavex_project_create" in (walked.diagnostics[0].hint or "")


def test_format_hints_speak_both_transports(tools: ArcavexTools, tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    assert tools.template_new(target=str(seed), name="seed").ok

    ambiguous = tools.layout_inspect(template=str(seed))  # two formats, none named

    [diag] = [d for d in ambiguous.diagnostics if d.code == "ARC-TPL-021"]
    assert "--format" in (diag.hint or "") and "'format'" in (diag.hint or ""), diag.hint
    assert "square" in (diag.hint or "") and "story" in (diag.hint or "")


def test_no_catalog_hint_an_mcp_caller_meets_speaks_only_in_cli_flags() -> None:
    """A ``--flag`` an MCP caller can meet must come with its MCP spelling.

    Skill installation and extension golden tests are operator commands with no MCP tool, so
    their entries may name flags alone; the render/authoring flags below have MCP arguments.
    """
    from arcavex.services.diagnostics_catalog import CATALOG

    shared = ("--format", "--locale", "--data", "--project", "--style", "--dpi")
    for code, doc in CATALOG.items():
        for text in (doc.summary, doc.fix):
            if any(flag in text for flag in shared):
                assert "MCP" in text, f"{code}: {text!r} names a CLI flag with no MCP spelling"


# ------------------------------------------------------------- patch ops are discoverable


def test_the_patch_tool_shows_one_example_op_per_verb(tools: ArcavexTools) -> None:
    """The op shape was discoverable only by failing ARC-TPL-092 until it was right."""
    description = tools.template_patch.__doc__ or ""

    assert '{"set": "nodes.<id>.<field>", "value":' in description
    assert '{"remove": "nodes.<id>[.<field>]"}' in description
    assert '"insert_before"' in description and '"insert_after"' in description
    assert '"node": {' in description


def test_the_patch_refusal_shows_the_same_shapes(tools: ArcavexTools, scaffold: Path) -> None:
    refused = tools.template_patch(str(scaffold), [PatchOp()])  # no verb at all

    [diag] = [d for d in refused.diagnostics if d.code == "ARC-TPL-092"]
    hint = diag.hint or ""
    assert "{set:" in hint and "value:" in hint, hint
    assert "{remove:" in hint, hint
    assert "insert_before" in hint and "node:" in hint, hint

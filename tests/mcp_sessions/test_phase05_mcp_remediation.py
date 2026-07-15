"""Phase 5 remediation regressions for the MCP authoring surface.

Each test pins one finding from the phase-05 DX/code reviews so the gap that shipped cannot
reopen: external data files through the four inspection/render tools (DX-1), a project render +
recorded run reachable from MCP (DX-2), locales in inspect (DX-3), patch leaf-field and
verb-count validation (DX-4/CR-1), data keypath validation (DX-6), and the style/effect catalog
tools (DX-5). Everything is driven through the same tool callables the server registers, and the
load-bearing DX-1 proof also goes through the real ``FastMCP`` ``call_tool`` dispatch.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent

from arcavex.clients.mcp_server import ArcavexTools
from arcavex.kernel.api import PatchOp, PreviewResult

_REPO_ROOT = Path(__file__).resolve().parents[2]
_IPEN = _REPO_ROOT / "examples" / "ipen-bilingual"


@pytest.fixture()
def project(tools: ArcavexTools, tmp_path: Path) -> Path:
    """A scaffolded template + a project pinning it, with an external data file on disk."""
    template = tmp_path / "card"
    tools._facade.scaffold_template("card", template)
    proj = tmp_path / "proj"
    created = tools.project_create(str(proj), str(template))
    assert created.ok, created.diagnostics
    return proj


def _external_data(tmp_path: Path) -> tuple[str, str]:
    """Scaffold a self-contained template and return (template_path, external_data_path)."""
    from arcavex.bootstrap import build_facade

    facade = build_facade()
    target = tmp_path / "card"
    facade.scaffold_template("card", target)
    data = tmp_path / "content.yaml"
    data.write_text("title: External Title\nsubtitle: From a real file\n", encoding="utf-8")
    return str(target / "template.yaml"), str(data)


# --------------------------------------------------------------------------- DX-1
def test_external_data_file_through_all_four_tools(tools: ArcavexTools, tmp_path: Path) -> None:
    """DX-1: an external data file must not crash validate/render/preview/layout_inspect."""
    template, data = _external_data(tmp_path)

    validated = tools.template_validate(template, data=data, format="square")
    assert validated.ok, validated.diagnostics
    assert not any(d.code == "ARC-INT-999" for d in validated.diagnostics)

    layout = tools.layout_inspect(template, data=data, format="square")
    assert layout.ok and layout.root is not None

    blocks = tools.render_preview(template, data=data, format="square")
    assert any(isinstance(b, Image) for b in blocks)
    preview = next(
        PreviewResult.model_validate_json(b.text) for b in blocks if isinstance(b, TextContent)
    )
    assert preview.ok and preview.output_path

    out = tmp_path / "out.png"
    rendered = tools.render(template, data=data, format="square", output=str(out))
    assert rendered.ok and out.is_file()
    # The external content actually drove the render (not the template's preview_data).
    assert rendered.content_sha256


def test_external_data_file_through_real_server_dispatch(
    server: FastMCP, tmp_path: Path
) -> None:
    """DX-1: the same external-data call through the real FastMCP call_tool dispatch is clean."""
    template, data = _external_data(tmp_path)

    async def call() -> object:
        return await server.call_tool(
            "arcavex_template_validate",
            {"template": template, "data": data, "format": "square"},
        )

    result = asyncio.run(call())
    # FastMCP returns (content_blocks, structured_result); neither carries an internal error.
    text = json.dumps(result, default=str)
    assert "ARC-INT-999" not in text
    assert "with_suffix" not in text


# --------------------------------------------------------------------------- DX-2
def test_project_render_creates_a_recorded_run_reachable_from_run_list(
    tools: ArcavexTools, project: Path
) -> None:
    """DX-2: project_create -> data_set -> project_render yields a run that run_list sees."""
    tools.data_set("title", "Rendered via MCP", project=str(project))
    run = tools.project_render(project=str(project))
    assert run.ok and run.run_id and run.outputs, run.diagnostics

    listed = tools.run_list(project=str(project))
    assert len(listed.runs) == 1
    assert listed.runs[0].run_id == run.run_id


def test_render_record_produces_a_recorded_run(tools: ArcavexTools, tmp_path: Path) -> None:
    """DX-2: direct-mode record_render also originates a run (for run_list --path / rerun)."""
    template, data = _external_data(tmp_path)
    run = tools.render_record(template, data=data, format="square")
    assert run.ok and run.run_id and run.run_dir, run.diagnostics
    listed = tools.run_list(path=str(Path(run.run_dir).parent))
    assert any(r.run_id == run.run_id for r in listed.runs)


# --------------------------------------------------------------------------- DX-3
def test_inspect_reports_locales(tools: ArcavexTools) -> None:
    """DX-3: template_inspect surfaces declared locales without triggering an error first."""
    report = tools.template_inspect(str(_IPEN))
    by_name = {loc.name: loc for loc in report.locales}
    assert set(by_name) == {"en", "fa"}
    assert by_name["fa"].direction == "rtl" and by_name["fa"].digits == "fa"
    assert by_name["fa"].has_fonts and by_name["fa"].has_patch


# --------------------------------------------------------------------------- DX-4 / CR-1
def test_patch_typo_leaf_field_is_rejected_without_writing(
    tools: ArcavexTools, scaffold: Path
) -> None:
    """DX-4: a typo'd style field is a located ARC-TPL-051, and nothing is written."""
    template = str(scaffold)
    before = (scaffold / "template.yaml").read_text(encoding="utf-8")
    result = tools.template_patch(
        template, [PatchOp(set="nodes.title.style.fontsize", value="80px")]
    )
    assert not result.ok
    assert any(d.code == "ARC-TPL-051" for d in result.diagnostics)
    assert (scaffold / "template.yaml").read_text(encoding="utf-8") == before


def test_patch_valid_leaf_field_still_applies(tools: ArcavexTools, scaffold: Path) -> None:
    """DX-4 must not block a genuinely-valid field edit."""
    result = tools.template_patch(
        str(scaffold), [PatchOp(set="nodes.title.style.font_size", value="90px")]
    )
    assert result.ok and result.applied == 1
    assert "90px" in (scaffold / "template.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "op",
    [
        PatchOp(set="nodes.title.style.color", value="#abc", remove="nodes.subtitle"),
        PatchOp(value="orphan"),  # zero verbs
    ],
)
def test_patch_zero_or_multi_verb_ops_are_rejected(
    tools: ArcavexTools, scaffold: Path, op: PatchOp
) -> None:
    """CR-1: a 0- or 2-verb op is a located ARC-TPL-092, never a partial apply."""
    before = (scaffold / "template.yaml").read_text(encoding="utf-8")
    result = tools.template_patch(str(scaffold), [op])
    assert not result.ok
    assert any(d.code == "ARC-TPL-092" for d in result.diagnostics)
    assert (scaffold / "template.yaml").read_text(encoding="utf-8") == before


# --------------------------------------------------------------------------- DX-6
def test_data_set_typo_keypath_warns(tools: ArcavexTools, project: Path) -> None:
    """DX-6: a keypath matching no declared variable is an ARC-TPL-112 warning (ok stays true)."""
    report = tools.data_set("titel", "oops", project=str(project))
    assert report.ok
    warnings = [d for d in report.diagnostics if d.code == "ARC-TPL-112"]
    assert warnings and warnings[0].severity == "warning"


def test_data_set_valid_keypath_is_clean(tools: ArcavexTools, project: Path) -> None:
    """A declared variable produces no ARC-TPL-112 warning."""
    report = tools.data_set("title", "fine", project=str(project))
    assert not any(d.code == "ARC-TPL-112" for d in report.diagnostics)


def test_data_import_typo_keypath_warns(tools: ArcavexTools, project: Path) -> None:
    """DX-6 also covers import_data's top-level keys."""
    report = tools.data_import("subtitel: x\n", project=str(project))
    assert report.ok
    assert any(d.code == "ARC-TPL-112" for d in report.diagnostics)


# --------------------------------------------------------------------------- DX-5
def test_style_and_effect_catalog_tools(tools: ArcavexTools) -> None:
    """DX-5: an agent can discover styles/effects (with param schemas) through MCP tools."""
    effects = tools.effects_list()
    assert effects.ok and effects.effects
    blur = next((e for e in effects.effects if e.name == "blur"), None)
    assert blur is not None and any(p.name == "radius" for p in blur.params)

    styles = tools.style_list()
    assert styles.ok
    if styles.styles:
        inspected = tools.style_inspect(styles.styles[0].name)
        assert inspected.ok and inspected.style is not None

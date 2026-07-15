"""The Phase 5 exit criterion (spec §8.5): an agent creates and CORRECTS a poster.

The agent uses ONLY supported template operations — no code path. It validates a seeded broken
template, reads the structured diagnostic, applies a path-addressed patch to fix it, confirms
the template is green, and renders the final PNG. Both the direct tool callables and the fully
built FastMCP server (via ``call_tool``) are exercised, so the correction loop is proven end to
end through the real MCP dispatch, not only the underlying functions.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.types import ImageContent

from arcavex.clients.mcp_server import ArcavexTools
from arcavex.kernel.api import PatchOp


def test_agent_creates_and_corrects_poster(tools: ArcavexTools, broken_template: Path) -> None:
    template = str(broken_template)

    # The agent validates and finds the poster broken, with a coded, structured diagnostic.
    initial = tools.template_validate(template, format="poster")
    assert not initial.ok
    invalid_color = [d for d in initial.diagnostics if d.code == "ARC-IR-030"]
    assert invalid_color, [d.code for d in initial.diagnostics]

    # It explains the code (structured help), then patches the addressed node's fill.
    help_ = tools.diagnostic_explain("ARC-IR-030")
    assert help_.found and help_.fix

    inspected = tools.template_inspect(template)
    assert "background" in {n.id for n in inspected.nodes}
    patched = tools.template_patch(
        template,
        [PatchOp(set="nodes.background.style.fill", value="#101024")],
        base_sha256=None,
    )
    assert patched.ok and patched.applied == 1

    # Re-validation is green — the correction used only a supported template operation.
    corrected = tools.template_validate(template, format="poster")
    assert corrected.ok and not any(d.is_error() for d in corrected.diagnostics)

    # And the poster now renders to a real PNG.
    out = broken_template / "poster.png"
    rendered = tools.render(template, format="poster", output=str(out))
    assert rendered.ok and out.is_file() and rendered.content_sha256


def test_correction_loop_through_the_live_server(server, broken_template: Path) -> None:
    """Drive the same loop through FastMCP ``call_tool`` to prove real MCP dispatch works."""
    import asyncio

    template = str(broken_template)

    def call_tool(name: str, args: dict):
        """call_tool is async; run each through a fresh event loop."""
        return asyncio.run(server.call_tool(name, args))

    # validate -> structured content carries the ARC-IR-030 diagnostic.
    args = {"template": template, "format": "poster"}
    _content, structured = call_tool("arcavex_template_validate", args)
    assert structured["ok"] is False
    assert any(d["code"] == "ARC-IR-030" for d in structured["diagnostics"])

    # patch the addressed node through the server.
    ops = [{"set": "nodes.background.style.fill", "value": "#101024"}]
    _c, patched = call_tool("arcavex_template_patch", {"template": template, "ops": ops})
    assert patched["ok"] is True and patched["applied"] == 1

    # revalidate green.
    _c, revalid = call_tool("arcavex_template_validate", args)
    assert revalid["ok"] is True

    # preview returns image content directly through the server.
    preview_content = call_tool("arcavex_render_preview", args)
    blocks = preview_content[0] if isinstance(preview_content, tuple) else preview_content
    assert any(isinstance(b, ImageContent) for b in blocks)
    # The structured PreviewResult travels as a JSON text block.
    text_block = next(b for b in blocks if getattr(b, "type", None) == "text")
    assert json.loads(text_block.text)["ok"] is True

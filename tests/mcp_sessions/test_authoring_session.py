"""The scripted authoring loop (spec §8.5 agent dogfood).

Drives the tool callables through the full loop an agent uses — inspect → patch → validate →
preview → inspect_layout → render — asserting each step returns the expected *structured*
result, never text. This is the proof that the MCP surface is a complete authoring path on its
own supported contracts.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import Image
from mcp.types import TextContent

from arcavex.clients.mcp_server import ArcavexTools
from arcavex.kernel.api import PatchOp, PreviewResult


def _preview_result(blocks: list) -> tuple[bool, PreviewResult]:
    """Split a render_preview result into (has_image, parsed PreviewResult)."""
    has_image = any(isinstance(b, Image) for b in blocks)
    text = next(b for b in blocks if isinstance(b, TextContent))
    return has_image, PreviewResult.model_validate_json(text.text)


def test_full_authoring_loop(tools: ArcavexTools, scaffold: Path) -> None:
    template = str(scaffold)

    # 1. inspect: read the contract and its stable node ids.
    inspected = tools.template_inspect(template)
    assert inspected.ok
    node_ids = {n.id for n in inspected.nodes}
    assert {"root", "title", "subtitle"} <= node_ids

    # 2. patch: recolor the title through its addressed node id, comment-preserving.
    before = (scaffold / "template.yaml").read_text(encoding="utf-8")
    patched = tools.template_patch(
        template, [PatchOp(set="nodes.title.style.color", value="#00ffcc")]
    )
    assert patched.ok and patched.applied == 1 and patched.sha256
    after = (scaffold / "template.yaml").read_text(encoding="utf-8")
    assert "#00ffcc" in after
    assert "self-contained card" in after  # a scaffold comment survived the round-trip

    # 3. validate: the edited template is still green.
    checked = tools.template_validate(template, format="square")
    assert checked.ok and not any(d.is_error() for d in checked.diagnostics)

    # 4. preview: image content is returned directly, plus a structured PreviewResult.
    has_image, preview = _preview_result(tools.render_preview(template, format="square"))
    assert has_image
    assert preview.ok and preview.output_path and Path(preview.output_path).is_file()

    # 5. layout inspect: resolved geometry, not text.
    layout = tools.layout_inspect(template, format="square")
    assert layout.ok and layout.root is not None
    assert layout.canvas_px == (1080, 1080)
    title = next(c for c in layout.root.children if c.id == "title")
    assert title.bounds_pt[2] > 0  # the title has a resolved width

    # 6. render: a real PNG on disk with a content hash.
    out = scaffold / "out.png"
    rendered = tools.render(template, format="square", output=str(out))
    assert rendered.ok and rendered.content_sha256 and out.is_file()

    # The patch changed the title color and left the rest of the file (comments, other nodes).
    assert before != after and "subtitle" in after


def test_preview_failure_returns_structured_diagnostics(
    tools: ArcavexTools, broken_template: Path
) -> None:
    """A failing preview yields no image but a structured PreviewResult with coded diagnostics."""
    has_image, preview = _preview_result(
        tools.render_preview(str(broken_template), format="poster")
    )
    assert not has_image
    assert not preview.ok
    assert any(d.code == "ARC-IR-030" for d in preview.diagnostics)


def test_data_and_asset_tools_round_trip(tools: ArcavexTools, tmp_path: Path) -> None:
    """set_data / import_data / asset_add / asset_annotate mirror the facade with diagnostics."""
    template = tmp_path / "card"
    tools._facade.scaffold_template("card", template)
    project = tmp_path / "proj"
    created = tools.project_create(str(project), str(template))
    assert created.ok

    set_report = tools.data_set("title", "From MCP", project=str(project))
    assert set_report.ok and set_report.path
    data_file = Path(set_report.path)
    assert "From MCP" in data_file.read_text(encoding="utf-8")

    imported = tools.data_import("subtitle: Imported\n", project=str(project))
    assert imported.ok
    assert "Imported" in data_file.read_text(encoding="utf-8")

    png = _tiny_png(tmp_path / "logo.png")
    added = tools.asset_add(str(png), project=str(project))
    assert added.ok and added.asset is not None
    annotated = tools.asset_annotate(added.asset.sha256, {"facing": "left"})
    assert annotated.ok and annotated.asset is not None
    assert annotated.asset.annotations == {"facing": "left"}


def _tiny_png(path: Path) -> Path:
    """Write a minimal valid 2x2 PNG and return its path."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path

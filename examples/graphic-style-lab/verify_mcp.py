"""Verify the Graphic Style Lab through Arcavex's real stdio MCP server.

Enable the bundled ``style-lab-filters`` extension in the active ``ARCAVEX_HOME`` first. The
script inspects, validates, previews, checks resolved layout, and renders all four deliverables
and all four demonstration sheets, then performs a byte-hash repeat check.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "output"
REPORT = OUTPUT / "mcp-report.json"
CASES = (
    {
        "name": "01-swiss-announcement",
        "template": "announcement-poster.yaml",
        "data": "data/announcement.yaml",
        "format": "portrait",
        "output": "01-swiss-announcement.jpg",
    },
    {
        "name": "02-xerox-video-thumbnail",
        "template": "video-thumbnail.yaml",
        "data": "data/video.yaml",
        "format": "thumbnail",
        "output": "02-xerox-video-thumbnail.jpg",
    },
    {
        "name": "03-cinema-movie-poster",
        "template": "movie-poster.yaml",
        "data": "data/movie.yaml",
        "format": "poster",
        "output": "03-cinema-movie-poster.jpg",
    },
    {
        "name": "04-riso-product-ad",
        "template": "product-ad.yaml",
        "data": "data/product.yaml",
        "format": "square",
        "output": "04-riso-product-ad.jpg",
    },
    *(
        {
            "name": data_name.removeprefix("reference-"),
            "template": "reference-sheet.yaml",
            "data": f"data/{data_name}.yaml",
            "format": "sheet",
            "output": f"{data_name}.png",
        }
        for data_name in (
            "reference-01-swiss",
            "reference-02-xerox",
            "reference-03-cinema",
            "reference-04-riso",
        )
    ),
)
EXPECTED_EFFECTS = {"swiss-cut", "xerox-pulse", "cinema-emulsion", "riso-register"}


def payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", []):
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return {}


def node_count(node: dict[str, Any] | None) -> int:
    if not node:
        return 0
    return 1 + sum(
        node_count(child)
        for child in node.get("children", [])
        if isinstance(child, dict)
    )


async def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    cli = ROOT / ".venv" / "bin" / "arcavex"
    command = str(cli) if cli.exists() else "arcavex"
    params = StdioServerParameters(command=command, args=["mcp", "serve"], cwd=str(ROOT), env=env)
    report: dict[str, Any] = {"cases": []}

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            report["server"] = initialized.serverInfo.model_dump()
            report["tool_count"] = len(tools.tools)

            effects = payload(await session.call_tool("arcavex_effects_list", {}))
            discovered = {item.get("name") for item in effects.get("effects", [])}
            report["effects"] = {
                "count": len(discovered),
                "expected": sorted(EXPECTED_EFFECTS),
                "all_discovered": EXPECTED_EFFECTS <= discovered,
            }

            for case in CASES:
                template = HERE / case["template"]
                data = HERE / case["data"]
                args = {
                    "template": str(template),
                    "data": str(data),
                    "format": case["format"],
                }
                inspected = payload(
                    await session.call_tool("arcavex_template_inspect", {"template": str(template)})
                )
                validated = payload(await session.call_tool("arcavex_template_validate", args))
                preview_result = await session.call_tool(
                    "arcavex_render_preview", {**args, "debug": False}
                )
                preview = payload(preview_result)
                layout = payload(await session.call_tool("arcavex_layout_inspect", args))
                rendered = payload(
                    await session.call_tool(
                        "arcavex_render",
                        {
                            **args,
                            "output": str(OUTPUT / case["output"]),
                            "debug": False,
                        },
                    )
                )
                report["cases"].append(
                    {
                        "name": case["name"],
                        "inspect_ok": inspected.get("ok"),
                        "node_count": len(inspected.get("nodes", [])),
                        "validate_ok": validated.get("ok"),
                        "preview_ok": preview.get("ok"),
                        "preview_image_blocks": sum(
                            getattr(block, "type", None) == "image"
                            for block in preview_result.content
                        ),
                        "layout_ok": layout.get("ok"),
                        "layout_nodes": node_count(layout.get("root")),
                        "layout_warnings": layout.get("warnings", []),
                        "render_ok": rendered.get("ok"),
                        "diagnostics": rendered.get("diagnostics", []),
                        "content_sha256": rendered.get("content_sha256"),
                        "output": case["output"],
                    }
                )

            first = CASES[0]
            repeat = payload(
                await session.call_tool(
                    "arcavex_render",
                    {
                        "template": str(HERE / first["template"]),
                        "data": str(HERE / first["data"]),
                        "format": first["format"],
                        "output": str(OUTPUT / "01-swiss-announcement-repeat.jpg"),
                        "debug": False,
                    },
                )
            )
            original = report["cases"][0]["content_sha256"]
            report["deterministic"] = repeat.get("content_sha256") == original
            report["repeat_sha256"] = repeat.get("content_sha256")

    report["all_ok"] = bool(
        report["effects"]["all_discovered"]
        and report["deterministic"]
        and all(
            case["inspect_ok"]
            and case["validate_ok"]
            and case["preview_ok"]
            and case["preview_image_blocks"] == 1
            and case["layout_ok"]
            and case["render_ok"]
            and not case["layout_warnings"]
            and not case["diagnostics"]
            for case in report["cases"]
        )
    )
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

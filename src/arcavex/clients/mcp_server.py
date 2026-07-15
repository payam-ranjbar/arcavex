"""The Arcavex MCP authoring surface (spec §6.2): a thin FastMCP server over the facade.

MCP is an OPTIONAL discovery/authoring transport, never a second engine. Every tool here is a
thin wrapper that delegates to one :class:`~arcavex.kernel.api.Facade` method and returns the
SAME versioned pydantic result model the CLI and Python API return — there is no parallel
schema and no capability reachable only through MCP (spec §12.18). Diagnostics travel as the
structured :class:`~arcavex.kernel.diagnostics.Diagnostic` model, never scraped console text, so
an agent inspects → patches → validates → previews → inspects layout → renders using only the
supported authoring contracts.

Transport is stdio only (no network). ``arcavex mcp serve`` runs the server; ``arcavex mcp
tools --json`` prints the tool catalog for discovery. This module is a client: it imports the
facade (and ``bootstrap`` to build one, exactly as the CLI does) and nothing from ``services``
or ``builtin``.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import (
    AssetReport,
    CheckResult,
    DataReport,
    DiagnosticHelp,
    DiffReport,
    Facade,
    LayoutReport,
    PatchOp,
    PatchTemplateResult,
    PreviewResult,
    ProjectListReport,
    ProjectResult,
    ProjectStatusReport,
    RenderResult,
    RerunReport,
    RunListReport,
    TemplateInspectReport,
    TemplateListReport,
)
from arcavex.kernel.diagnostics import has_errors

_INSTRUCTIONS = (
    "Arcavex rendering engine, MCP authoring surface. Every tool mirrors a service API method "
    "and returns a structured, versioned result (with a 'diagnostics' list of coded, located "
    "diagnostics — never free text). Typical loop: arcavex_template_inspect to read the "
    "contract and its node ids, arcavex_template_patch to edit an addressed node, "
    "arcavex_template_validate to check, arcavex_render_preview to see the image, "
    "arcavex_layout_inspect to read resolved geometry, arcavex_render to write the final PNG. "
    "Use arcavex_diagnostic_explain <code> for any diagnostic you do not recognize."
)


class ArcavexTools:
    """The tool implementations: each method delegates to exactly one facade method.

    Kept as bound methods (not free closures) so tests can drive the exact same callables the
    server registers — a tool cannot diverge from what is tested. Path-like inputs are plain
    strings (clean JSON schemas); the facade converts them to ``Path``.
    """

    def __init__(self, facade: Facade) -> None:
        """Bind the tools to a wired facade."""
        self._facade = facade

    # ---------------------------------------------------------------- templates
    def template_list(self) -> TemplateListReport:
        """List every published library template and its available versions."""
        return self._facade.list_templates()

    def template_inspect(self, template: str) -> TemplateInspectReport:
        """Report a template's contract: variables, formats, node ids, functions, preview data."""
        return self._facade.inspect_template(template)  # type: ignore[arg-type]

    def template_validate(
        self,
        template: str,
        data: str | None = None,
        format: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> CheckResult:
        """Validate a template (schema, structure, expressions, layout) and return diagnostics."""
        diagnostics = self._facade.validate_template(
            template,  # type: ignore[arg-type]
            data=data,  # type: ignore[arg-type]
            format_name=format,
            locale=locale,
            style=style,
        )
        return CheckResult(ok=not has_errors(diagnostics), diagnostics=diagnostics)

    def template_patch(
        self, template: str, ops: list[PatchOp], base_sha256: str | None = None
    ) -> PatchTemplateResult:
        """Apply path-addressed set/remove/insert ops to a template file (comment-preserving).

        Each op addresses a stable authored node id ('nodes.<id>[.<field>...]'). Pass the
        'sha256' from a prior inspect/patch as 'base_sha256' to reject a concurrent edit.
        """
        return self._facade.patch_template(template, ops, base_sha256)  # type: ignore[arg-type]

    # ---------------------------------------------------------------- projects
    def project_create(
        self,
        target: str,
        template: str,
        name: str | None = None,
        style: str | None = None,
        formats: list[str] | None = None,
        locales: list[str] | None = None,
    ) -> ProjectResult:
        """Scaffold a project at 'target' pinning a template reference or path."""
        from pathlib import Path

        return self._facade.create_project(
            Path(target), name or Path(target).name, template,
            style=style, formats=formats, locales=locales,
        )

    def project_list(self, root: str | None = None) -> ProjectListReport:
        """List projects discovered under 'root' (its own project.yaml and immediate children)."""
        return self._facade.list_projects(root)  # type: ignore[arg-type]

    def project_status(self, project: str | None = None) -> ProjectStatusReport:
        """Report the active (or --project) project's manifest and recorded-run count."""
        return self._facade.project_status(project=project)  # type: ignore[arg-type]

    def project_clone(
        self, target: str, name: str | None = None, project: str | None = None
    ) -> ProjectResult:
        """Clone the active (or 'project') project into 'target', reset to draft."""
        from pathlib import Path

        return self._facade.clone_project(
            Path(target), name or Path(target).name, project=project,  # type: ignore[arg-type]
        )

    # ---------------------------------------------------------------- data & assets
    def data_set(
        self, keypath: str, value: Any, project: str | None = None
    ) -> DataReport:
        """Set a single value at a dotted 'keypath' in the project's data, then revalidate."""
        return self._facade.set_data(keypath, value, project=project)  # type: ignore[arg-type]

    def data_import(
        self, yaml_text: str, locale: str | None = None, project: str | None = None
    ) -> DataReport:
        """Merge a YAML data document into the project's data (overlay semantics), then validate."""
        return self._facade.import_data(
            yaml_text, locale=locale, project=project,  # type: ignore[arg-type]
        )

    def asset_add(self, source: str, project: str | None = None) -> AssetReport:
        """Ingest an image into the workspace content-addressed store and return its reference."""
        from pathlib import Path

        return self._facade.add_asset(Path(source), project=project)  # type: ignore[arg-type]

    def asset_annotate(
        self, sha256: str, annotations: dict[str, Any]
    ) -> AssetReport:
        """Write sidecar annotations (facing/focal_point/tags) onto an ingested asset."""
        return self._facade.annotate_asset(sha256, annotations)

    # ---------------------------------------------------------------- render & inspect
    def render_preview(
        self,
        template: str,
        data: str | None = None,
        format: str | None = None,
        locale: str | None = None,
        style: str | None = None,
        dpi: int | None = None,
        debug: bool = False,
    ) -> list[Image | TextContent]:
        """Render a template to a preview PNG and return the image plus structured diagnostics.

        Returns MCP image content directly (base64 PNG) so the agent sees the render, followed by
        a JSON block carrying the structured PreviewResult (ok, timings, diagnostics, path). With
        debug=true the image carries the layout overlay (node ids, bounds, baselines, anchors).
        On a compile/layout failure no image is produced; the PreviewResult block explains why.
        """
        result: PreviewResult = self._facade.render_preview(
            template,  # type: ignore[arg-type]
            data,  # type: ignore[arg-type]
            format,
            locale=locale,
            style=style,
            dpi=dpi,
            debug=debug,
        )
        blocks: list[Image | TextContent] = []
        if result.ok and result.output_path:
            blocks.append(Image(path=result.output_path))
        blocks.append(
            TextContent(type="text", text=result.model_dump_json(exclude_none=True))
        )
        return blocks

    def layout_inspect(
        self,
        template: str,
        data: str | None = None,
        format: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> LayoutReport:
        """Report resolved geometry: per-node bounds, anchor derivations, overflow, overlaps."""
        return self._facade.inspect_layout(
            template,  # type: ignore[arg-type]
            data,  # type: ignore[arg-type]
            format,
            locale=locale,
            style=style,
        )

    def render(
        self,
        template: str,
        data: str | None = None,
        format: str | None = None,
        locale: str | None = None,
        style: str | None = None,
        output: str | None = None,
        dpi: int | None = None,
        debug: bool = False,
    ) -> RenderResult:
        """Render a template to a PNG file on disk; return the path, content hash, diagnostics."""
        from pathlib import Path

        return self._facade.render_file(
            template=template,  # type: ignore[arg-type]
            data=data,  # type: ignore[arg-type]
            format_name=format,
            locale=locale,
            style=style,
            output=Path(output) if output else None,
            dpi=dpi,
            debug=debug,
        )

    # ---------------------------------------------------------------- runs
    def run_list(
        self, project: str | None = None, path: str | None = None
    ) -> RunListReport:
        """List recorded runs for the active (or --project) project, or under an outputs 'path'."""
        return self._facade.list_runs(project=project, path=path)  # type: ignore[arg-type]

    def run_diff(self, run_a: str, run_b: str) -> DiffReport:
        """Diff two recorded runs: per-output pixels/perceptual plus provenance metadata."""
        from pathlib import Path

        return self._facade.diff_runs(Path(run_a), Path(run_b))

    def run_rerun(self, run_dir: str) -> RerunReport:
        """Reproduce a recorded run into a new run directory (byte-identical on match)."""
        from pathlib import Path

        return self._facade.rerun(Path(run_dir))

    # ---------------------------------------------------------------- diagnostics
    def diagnostic_explain(self, code: str) -> DiagnosticHelp:
        """Explain a diagnostic code: what it means and the typical fix."""
        return self._facade.explain_diagnostic(code)


# The tool catalog: MCP tool name -> the ArcavexTools method it wraps. One registration site so
# the catalog, the server, and the tests all read from a single source of truth.
_TOOL_METHODS: tuple[tuple[str, str], ...] = (
    ("arcavex_template_list", "template_list"),
    ("arcavex_template_inspect", "template_inspect"),
    ("arcavex_template_validate", "template_validate"),
    ("arcavex_template_patch", "template_patch"),
    ("arcavex_project_create", "project_create"),
    ("arcavex_project_list", "project_list"),
    ("arcavex_project_status", "project_status"),
    ("arcavex_project_clone", "project_clone"),
    ("arcavex_data_set", "data_set"),
    ("arcavex_data_import", "data_import"),
    ("arcavex_asset_add", "asset_add"),
    ("arcavex_asset_annotate", "asset_annotate"),
    ("arcavex_render_preview", "render_preview"),
    ("arcavex_layout_inspect", "layout_inspect"),
    ("arcavex_render", "render"),
    ("arcavex_run_list", "run_list"),
    ("arcavex_run_diff", "run_diff"),
    ("arcavex_run_rerun", "run_rerun"),
    ("arcavex_diagnostic_explain", "diagnostic_explain"),
)


def build_mcp_server(facade: Facade | None = None) -> FastMCP:
    """Build the FastMCP server, registering every tool over a (possibly injected) facade.

    A caller may inject a facade (tests, or a host that already built one); otherwise one is
    built via :func:`~arcavex.bootstrap.build_facade`, exactly as the CLI does. ``render_preview``
    opts out of structured output because it returns mixed image + text content.
    """
    tools = ArcavexTools(facade if facade is not None else build_facade())
    server = FastMCP("arcavex", instructions=_INSTRUCTIONS)
    for tool_name, method_name in _TOOL_METHODS:
        method = getattr(tools, method_name)
        structured = None if method_name != "render_preview" else False
        server.tool(name=tool_name, structured_output=structured)(method)
    return server


def tool_catalog(server: FastMCP) -> list[dict[str, Any]]:
    """Return the server's tool catalog (name, description, input/output JSON schemas).

    Backs ``arcavex mcp tools --json`` — the discovery surface an agent (or a human wiring the
    server) reads to learn the available tools and their exact schemas.
    """
    listed = _run_async(server.list_tools())
    catalog: list[dict[str, Any]] = []
    for tool in listed:
        catalog.append(
            {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "inputSchema": tool.inputSchema,
                "outputSchema": tool.outputSchema,
            }
        )
    return catalog


def _run_async(coro: Any) -> Any:
    """Run a coroutine to completion from sync code (no event loop is expected to be running)."""
    import asyncio

    return asyncio.run(coro)


def serve(facade: Facade | None = None) -> None:
    """Run the MCP server over stdio (blocking) — the ``arcavex mcp serve`` entry point."""
    build_mcp_server(facade).run(transport="stdio")


def catalog_json(facade: Facade | None = None) -> str:
    """Return the tool catalog as pretty JSON — the ``arcavex mcp tools --json`` payload."""
    catalog = tool_catalog(build_mcp_server(facade))
    return json.dumps(
        {"response_version": 1, "tools": catalog}, ensure_ascii=False, indent=2
    )

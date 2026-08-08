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

Path-like tool inputs are declared as plain strings (clean JSON schemas) and coerced to
``Path`` here at the boundary before the facade is called — the facade's typed signatures
expect ``Path``, so the coercion cannot be skipped for any path argument (DX-1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import (
    AssetReport,
    AutomationMode,
    CheckResult,
    DataReport,
    DiagnosticHelp,
    DiffReport,
    EffectListReport,
    EngineHandshakeReport,
    ExtensionMode,
    Facade,
    FontListReport,
    HitTestReport,
    LayerTreeReport,
    LayoutReport,
    PatchOp,
    PatchTemplateResult,
    PreviewResult,
    ProjectListReport,
    ProjectPolicyReport,
    ProjectResult,
    ProjectSnapshotReport,
    ProjectStatusReport,
    ProjectUIMetadata,
    ProjectUIMetadataReport,
    ProposalActionReport,
    ProposalListReport,
    RenderResult,
    RerunReport,
    RunListReport,
    RunReport,
    StyleInspectReport,
    StyleListReport,
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
    "To author real content, scaffold with arcavex_project_create, write data with "
    "arcavex_data_set / arcavex_data_import, then arcavex_project_render for a recorded run "
    "(discoverable via arcavex_run_list). Discover vocabulary with arcavex_style_list / "
    "arcavex_effects_list / arcavex_font_list (the only font families a template may name). "
    "Use arcavex_diagnostic_explain <code> for any code you do not know."
)


def _opt_path(value: str | None) -> Path | None:
    """Coerce an optional path-like tool argument to ``Path`` (``None`` stays ``None``)."""
    return Path(value) if value else None


class ArcavexTools:
    """The tool implementations: each method delegates to exactly one facade method.

    Kept as bound methods (not free closures) so tests can drive the exact same callables the
    server registers — a tool cannot diverge from what is tested. Path-like inputs are plain
    strings in the schema and are converted to ``Path`` here before the facade is called.
    """

    def __init__(self, facade: Facade) -> None:
        """Bind the tools to a wired facade."""
        self._facade = facade

    # ---------------------------------------------------------------- desktop
    def engine_handshake(self) -> EngineHandshakeReport:
        """Report engine identity, compatibility versions, capabilities, paths, and health."""
        return self._facade.engine_handshake()

    # ---------------------------------------------------------------- templates
    def template_list(self) -> TemplateListReport:
        """List every published library template and its available versions."""
        return self._facade.list_templates()

    def template_inspect(self, template: str) -> TemplateInspectReport:
        """Report a template's contract: variables, formats, locales, node ids, functions, data."""
        return self._facade.inspect_template(Path(template))

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
            Path(template),
            data=_opt_path(data),
            format_name=format,
            locale=locale,
            style=style,
        )
        return CheckResult(ok=not has_errors(diagnostics), diagnostics=diagnostics)

    def template_patch(
        self, template: str, ops: list[PatchOp], base_sha256: str | None = None
    ) -> PatchTemplateResult:
        """Apply path-addressed set/remove/insert ops to a template file (comment-preserving).

        Each op addresses a stable authored node id ('nodes.<id>[.<field>]') and names exactly
        one verb; a leaf field in a fixed-vocabulary block (style/fit/paragraph/constraints) is
        checked before writing, so a typo is a located diagnostic rather than a silent write.
        Pass the 'sha256' from a prior inspect/patch as 'base_sha256' to reject a concurrent edit.
        """
        return self._facade.patch_template(Path(template), ops, base_sha256)

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
        return self._facade.create_project(
            Path(target), name or Path(target).name, template,
            style=style, formats=formats, locales=locales,
        )

    def project_list(self, root: str | None = None) -> ProjectListReport:
        """List projects discovered under 'root' (its own project.yaml and immediate children)."""
        return self._facade.list_projects(_opt_path(root))

    def project_status(self, project: str | None = None) -> ProjectStatusReport:
        """Report the active (or --project) project's manifest and recorded-run count."""
        return self._facade.project_status(project=_opt_path(project))

    def project_snapshot(self, project: str | None = None) -> ProjectSnapshotReport:
        """Open a project read-only and report its source and render revision manifests."""
        return self._facade.project_snapshot(project=_opt_path(project))

    def layer_tree(
        self,
        project: str | None = None,
        mode: Literal["authored", "rendered"] = "authored",
        format: str | None = None,
        locale: str | None = None,
    ) -> LayerTreeReport:
        """Return the engine-owned definition or rendered hierarchy for one project target."""
        return self._facade.layer_tree(
            project=_opt_path(project), mode=mode, format_name=format, locale=locale
        )

    def hit_test(
        self,
        x_pt: float | str,
        y_pt: float | str,
        project: str | None = None,
        format: str | None = None,
        locale: str | None = None,
    ) -> HitTestReport:
        """Return topmost-first rendered candidates containing one canvas point coordinate."""
        return self._facade.hit_test(
            project=_opt_path(project),
            x_pt=x_pt,
            y_pt=y_pt,
            format_name=format,
            locale=locale,
        )

    def project_ui_metadata(
        self, project: str | None = None
    ) -> ProjectUIMetadataReport:
        """Read project-owned non-rendering layer and workspace metadata."""
        return self._facade.project_ui_metadata(project=_opt_path(project))

    def project_ui_metadata_set(
        self, metadata: ProjectUIMetadata, project: str | None = None
    ) -> ProjectUIMetadataReport:
        """Atomically replace validated project-owned editor metadata."""
        return self._facade.set_project_ui_metadata(
            metadata, project=_opt_path(project)
        )

    def project_policy(self, project: str | None = None) -> ProjectPolicyReport:
        """Return effective project automation and extension policy."""
        return self._facade.project_policy(project=_opt_path(project))

    def project_policy_set(
        self,
        mode: AutomationMode,
        extensions: ExtensionMode,
        project: str | None = None,
    ) -> ProjectPolicyReport:
        """Atomically set project automation and extension policy."""
        return self._facade.set_project_policy(
            mode, extensions, project=_opt_path(project)
        )

    def project_proposal_list(
        self, project: str | None = None
    ) -> ProposalListReport:
        """List deterministic proposal records and malformed-entry diagnostics."""
        return self._facade.list_project_proposals(project=_opt_path(project))

    def project_proposal_approve(
        self, command_id: str, project: str | None = None
    ) -> ProposalActionReport:
        """Authorize a current proposal without claiming its command was applied."""
        return self._facade.approve_project_proposal(
            command_id, project=_opt_path(project)
        )

    def project_proposal_reject(
        self, command_id: str, reason: str, project: str | None = None
    ) -> ProposalActionReport:
        """Persist an explicit proposal rejection without deleting its record."""
        return self._facade.reject_project_proposal(
            command_id, reason, project=_opt_path(project)
        )

    def project_clone(
        self, target: str, name: str | None = None, project: str | None = None
    ) -> ProjectResult:
        """Clone the active (or 'project') project into 'target', reset to draft."""
        return self._facade.clone_project(
            Path(target), name or Path(target).name, project=_opt_path(project),
        )

    def project_render(
        self,
        project: str | None = None,
        formats: list[str] | None = None,
        locales: list[str] | None = None,
        dpi: int | None = None,
    ) -> RunReport:
        """Render the active (or 'project') project's formats × locales into a recorded run.

        This is the project-mode render an agent uses after project_create + data_set/data_import:
        it produces a recorded run (manifest + provenance) that run_list/run_diff/run_rerun then
        operate on. Direct-file mode (a template + data) uses arcavex_render instead.
        """
        return self._facade.render_project(
            project=_opt_path(project), formats=formats, locales=locales, dpi=dpi
        )

    def render_record(
        self,
        template: str,
        data: str | None = None,
        format: str | None = None,
        locale: str | None = None,
        style: str | None = None,
        dpi: int | None = None,
    ) -> RunReport:
        """Render a template + data directly with a recorded run manifest (like 'render --record').

        Direct-mode counterpart to arcavex_project_render: produces a recorded run (provenance,
        reproducible) without a project, so run_list --path / run_rerun / run_diff have a run to
        act on. Use arcavex_render for a one-off PNG with no recorded run.
        """
        return self._facade.record_render(
            Path(template),
            data=_opt_path(data),
            format_name=format,
            locale=locale,
            style=style,
            dpi=dpi,
        )

    # ---------------------------------------------------------------- data & assets
    def data_set(
        self, keypath: str, value: Any, project: str | None = None
    ) -> DataReport:
        """Set a single value at a dotted 'keypath' in the project's data, then revalidate."""
        return self._facade.set_data(keypath, value, project=_opt_path(project))

    def data_import(
        self, yaml_text: str, locale: str | None = None, project: str | None = None
    ) -> DataReport:
        """Merge a YAML data document into the project's data (overlay semantics), then validate."""
        return self._facade.import_data(yaml_text, locale=locale, project=_opt_path(project))

    def asset_add(self, source: str, project: str | None = None) -> AssetReport:
        """Ingest an image into the workspace content-addressed store and return its reference."""
        return self._facade.add_asset(Path(source), project=_opt_path(project))

    def asset_annotate(
        self, sha256: str, annotations: dict[str, Any]
    ) -> AssetReport:
        """Write sidecar annotations (facing/focal_point/tags) onto an ingested asset."""
        return self._facade.annotate_asset(sha256, annotations)

    # ---------------------------------------------------------------- catalogs
    def style_list(self) -> StyleListReport:
        """List every installed style pack (palettes, fonts, effect presets, role defaults)."""
        return self._facade.list_styles()

    def style_inspect(self, name: str) -> StyleInspectReport:
        """Report one style pack's palettes, fonts, effect presets, and role defaults."""
        return self._facade.inspect_style(name)

    def effects_list(self) -> EffectListReport:
        """List every registered effect, its category, and each param's type/default/range."""
        return self._facade.list_effects()

    def font_list(self) -> FontListReport:
        """List every font family a template may name, marking bundled vs locally installed.

        Rendering is confined to these families (there is no system-font fallback, for
        determinism), so this is the legal vocabulary for 'style.font' — naming anything else is
        ARC-RND-010. Installing a font is a local operator action, not an agent one: ask the user
        to run 'arcavex font add <path/to/font.ttf>'.
        """
        return self._facade.list_fonts()

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
            Path(template),
            _opt_path(data),
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
            Path(template),
            _opt_path(data),
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
        return self._facade.render_file(
            template=Path(template),
            data=_opt_path(data),
            format_name=format,
            locale=locale,
            style=style,
            output=_opt_path(output),
            dpi=dpi,
            debug=debug,
        )

    # ---------------------------------------------------------------- runs
    def run_list(
        self, project: str | None = None, path: str | None = None
    ) -> RunListReport:
        """List recorded runs for the active (or --project) project, or under an outputs 'path'."""
        return self._facade.list_runs(project=_opt_path(project), path=_opt_path(path))

    def run_diff(self, run_a: str, run_b: str) -> DiffReport:
        """Diff two recorded runs: per-output pixels/perceptual plus provenance metadata."""
        return self._facade.diff_runs(Path(run_a), Path(run_b))

    def run_rerun(self, run_dir: str) -> RerunReport:
        """Reproduce a recorded run into a new run directory (byte-identical on match)."""
        return self._facade.rerun(Path(run_dir))

    # ---------------------------------------------------------------- diagnostics
    def diagnostic_explain(self, code: str) -> DiagnosticHelp:
        """Explain a diagnostic code: what it means and the typical fix."""
        return self._facade.explain_diagnostic(code)


# The tool catalog: MCP tool name -> the ArcavexTools method it wraps. One registration site so
# the catalog, the server, and the tests all read from a single source of truth.
_TOOL_METHODS: tuple[tuple[str, str], ...] = (
    ("engine_handshake", "engine_handshake"),
    ("arcavex_template_list", "template_list"),
    ("arcavex_template_inspect", "template_inspect"),
    ("arcavex_template_validate", "template_validate"),
    ("arcavex_template_patch", "template_patch"),
    ("arcavex_project_create", "project_create"),
    ("arcavex_project_list", "project_list"),
    ("arcavex_project_status", "project_status"),
    ("project_snapshot", "project_snapshot"),
    ("layer_tree", "layer_tree"),
    ("hit_test", "hit_test"),
    ("project_ui_metadata", "project_ui_metadata"),
    ("project_ui_metadata_set", "project_ui_metadata_set"),
    ("project_policy", "project_policy"),
    ("project_policy_set", "project_policy_set"),
    ("project_proposal_list", "project_proposal_list"),
    ("project_proposal_approve", "project_proposal_approve"),
    ("project_proposal_reject", "project_proposal_reject"),
    ("arcavex_project_clone", "project_clone"),
    ("arcavex_project_render", "project_render"),
    ("arcavex_render_record", "render_record"),
    ("arcavex_data_set", "data_set"),
    ("arcavex_data_import", "data_import"),
    ("arcavex_asset_add", "asset_add"),
    ("arcavex_asset_annotate", "asset_annotate"),
    ("arcavex_style_list", "style_list"),
    ("arcavex_style_inspect", "style_inspect"),
    ("arcavex_effects_list", "effects_list"),
    ("arcavex_font_list", "font_list"),
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

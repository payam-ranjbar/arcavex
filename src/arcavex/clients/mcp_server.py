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

Tool ARGUMENTS are under the same contract as tool results. The SDK builds each tool's argument
model from the function signature with pydantic's default of ignoring unknown keys, and reports
a failed validation as raw pydantic prose; an assistant that passed ``format`` to a tool without
one was told ok:true and believed it. Here every argument key must be declared (the published
inputSchema says so with ``additionalProperties: false``), and an unknown, missing, or mistyped
argument is refused before dispatch with the coded ``ARC-MCP-00x`` envelope every other refusal
uses. Each parameter carries a description, because the schema is the only manual a connecting
client has.
"""

from __future__ import annotations

import difflib
import json
import warnings
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

# pydantic-settings >= 2.15 warns about an incomplete field in FastMCP's own settings model, at
# import and again every time a server is constructed. It is the SDK's to fix; to a person who has
# just typed `arcavex mcp serve` for the first time, a warning on stderr at every spawn reads as
# "it is broken", so keep it off their terminal -- here for the import, and in `build_mcp_server`
# for the construction, which is the one a person actually meets.
# Older pydantic-settings has neither the warning nor the class that names it.
try:
    from pydantic_settings import IncompleteFieldDefinitionWarning as _SettingsWarning
except ImportError:  # pragma: no cover - depends on the resolved pydantic-settings
    _SettingsWarning = None  # type: ignore[assignment,misc]
with warnings.catch_warnings():
    if _SettingsWarning is not None:
        warnings.simplefilter("ignore", _SettingsWarning)
    from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.tools import Tool
from mcp.types import CallToolResult, ContentBlock, TextContent
from pydantic import ConfigDict, Field, ValidationError

from arcavex import __version__
from arcavex.bootstrap import build_facade
from arcavex.kernel.api import (
    AssetReport,
    AutomationMode,
    CheckResult,
    DataReport,
    DetachReport,
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
    PreviewProjectReport,
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
    PublishReport,
    RenderResult,
    RerunReport,
    RunListReport,
    RunReport,
    ScaffoldResult,
    ShapeListReport,
    StyleInspectReport,
    StyleListReport,
    TemplateInspectReport,
    TemplateListReport,
)
from arcavex.kernel.diagnostics import Diagnostic, diagnostic, has_errors
from arcavex.kernel.editor import HistoryReport, TransactionReport


@contextmanager
def _without_the_sdks_settings_warning() -> Iterator[None]:
    """Suppress that one warning category, and nothing else, for the block."""
    with warnings.catch_warnings():
        if _SettingsWarning is not None:
            warnings.simplefilter("ignore", _SettingsWarning)
        yield


_INSTRUCTIONS = (
    "Arcavex: a deterministic poster/graphic rendering engine. You are talking to it over MCP. "
    "FIRST, read the resource skill://arcavex-design-studio/SKILL.md — the design skill shipped "
    "with this engine; its references/ cover the authoring loop, art direction, multi-format and "
    "locale work, and verification. Then: "
    "STARTING FROM NOTHING — arcavex_template_new scaffolds a minimal renderable template; "
    "arcavex_project_create makes a project around a template (a path, or a library name after "
    "arcavex_template_publish); arcavex_data_set / arcavex_data_import write its content; "
    "arcavex_project_render writes a recorded run (see arcavex_run_list). "
    "THE LOOP ON AN EXISTING DESIGN — arcavex_template_inspect reads the contract and node ids; "
    "arcavex_template_patch edits an addressed node; arcavex_template_validate checks; "
    "arcavex_render_preview returns the picture as image content (pass dpi=96, or max_px, while "
    "iterating); arcavex_layout_inspect reads resolved geometry and overlaps; arcavex_render "
    "writes the final file. For semantic edits with undo, use arcavex_editor_apply (and _undo / "
    "_redo / _history): it takes a whole transaction, checks the project revision, and writes "
    "atomically; submit an empty transaction to have the engine state the exact shape it wants. "
    "VOCABULARY — arcavex_style_list, arcavex_effects_list, arcavex_shape_list (the 'generator:' "
    "names a shape node may use, with their params), arcavex_font_list (the only font families "
    "a template may name). Every tool returns a structured, versioned result with a "
    "'diagnostics' list of coded, located diagnostics; arcavex_diagnostic_explain <code> explains "
    "any code. Tool arguments are checked before anything runs: an unknown, missing, or mistyped "
    "argument is refused with ARC-MCP-010/002/003 and a hint naming the accepted arguments, so an "
    "option that does not exist can never look like it took effect. Tools without the arcavex_ "
    "prefix (project_snapshot, layer_tree, hit_test, project_policy…) serve Arcavex Desktop's "
    "live view and are not needed for authoring."
)


def _opt_path(value: str | None) -> Path | None:
    """Coerce an optional path-like tool argument to ``Path`` (``None`` stays ``None``)."""
    return Path(value) if value else None


# --------------------------------------------------------------------- parameter descriptions
# FastMCP copies a pydantic ``Field(description=...)`` into the tool's inputSchema, so these are
# what a connecting assistant reads about each argument: what it is, its unit or accepted values,
# and what a path is relative to. Shapes shared by several tools are named once.
_RELATIVE = "absolute, or relative to the server's working directory"
_PROJECT_DIR = (
    f"Project directory (the one holding project.yaml); {_RELATIVE}. Omit to use the project "
    "found by walking up from the server's working directory."
)
_Project = Annotated[str | None, Field(description=_PROJECT_DIR)]
_ProjectOrCwd = Annotated[
    str | None,
    Field(
        description=f"Project directory (the one holding project.yaml); {_RELATIVE}. Omit for "
        "the server's working directory."
    ),
]
_Template = Annotated[
    str,
    Field(
        description="Template to use: a template.yaml file or a directory holding one; "
        f"{_RELATIVE}."
    ),
]
_Data = Annotated[
    str | None,
    Field(
        description=f"YAML data file supplying the template's variables; {_RELATIVE}. Omit to "
        "render the template's own preview_data."
    ),
]
_Format = Annotated[
    str | None,
    Field(
        description="Format name declared under the template's 'formats:' "
        "(arcavex_template_inspect lists them). Required when the template declares more than "
        "one."
    ),
]
_Locale = Annotated[
    str | None,
    Field(
        description="Locale name declared under the template's 'locales:' "
        "(arcavex_template_inspect lists them); omit for the source language."
    ),
]
_Style = Annotated[
    str | None,
    Field(
        description="Style pack name from arcavex_style_list, overriding the template's 'style:'."
    ),
]
_Dpi = Annotated[
    int | None,
    Field(
        description="Render DPI as an integer, overriding the format's declared canvas dpi; omit "
        "to render at the declared dpi."
    ),
]
_Formats = Annotated[
    list[str] | None,
    Field(
        description="Format names to act on, from the project's project.yaml; omit for every "
        "declared format."
    ),
]
_Locales = Annotated[
    list[str] | None,
    Field(
        description="Locale names to act on, from the project's project.yaml; omit for every "
        "declared locale (the source language alone when none is declared)."
    ),
]
_Debug = Annotated[
    bool,
    Field(
        description="Draw the layout overlay (node ids, bounds, baselines, anchors) on the image."
    ),
]
_CommandId = Annotated[
    str, Field(description="The proposal's command_id (a uuid4) from project_proposal_list.")
]
_TargetFormat = Annotated[
    str | None,
    Field(
        description="Format name from the project's project.yaml; omit for the project's first "
        "declared format."
    ),
]


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

    def template_inspect(self, template: _Template) -> TemplateInspectReport:
        """Report a template's contract: variables, formats, locales, node ids, functions, data."""
        return self._facade.inspect_template(Path(template))

    def template_new(
        self,
        target: Annotated[
            str,
            Field(
                description=f"Directory to create the template in (created if absent); {_RELATIVE}."
            ),
        ],
        name: Annotated[
            str | None,
            Field(
                description="Template name written into the scaffold; defaults to the target "
                "directory's name."
            ),
        ] = None,
        formats: Annotated[
            list[str] | None,
            Field(
                description="Canvas presets to declare: square, story, portrait, landscape (px at "
                "96 dpi) and a4, a3, a2, letter, tabloid (mm at 300 dpi with a 3mm bleed). "
                "Defaults to square + story; any other canvas can be added afterwards with "
                "arcavex_template_patch ('set': 'formats.<name>')."
            ),
        ] = None,
    ) -> ScaffoldResult:
        """Scaffold a minimal renderable template directory to start a new design from."""
        return self._facade.scaffold_template(name or Path(target).name, Path(target), formats)

    def template_publish(
        self,
        template: _Template,
        name: Annotated[
            str,
            Field(
                description="Library name to publish under; arcavex_project_create then pins it "
                "as '<name>' or '<name>@<version>'."
            ),
        ],
        version: Annotated[
            str,
            Field(
                description="Dotted version such as '1.0.0'; a published version is immutable."
            ),
        ],
        set_default: Annotated[
            bool,
            Field(description="Make this version the one a bare library name resolves to."),
        ] = True,
    ) -> PublishReport:
        """Publish a template directory into the library as an immutable version."""
        return self._facade.publish_template(Path(template), name, version, set_default)

    def template_detach(self, project: _Project = None) -> DetachReport:
        """Copy the project's pinned template into the project so it can be edited in place."""
        return self._facade.detach_template(project=_opt_path(project))

    def template_validate(
        self,
        template: _Template,
        data: _Data = None,
        format: _Format = None,
        locale: _Locale = None,
        style: _Style = None,
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
        self,
        template: _Template,
        ops: Annotated[
            list[PatchOp],
            Field(
                description="Patch operations applied in order; one verb each, in the shapes "
                "this tool's description shows."
            ),
        ],
        base_sha256: Annotated[
            str | None,
            Field(
                description="The template's 'sha256' from a prior arcavex_template_inspect or "
                "arcavex_template_patch; the patch is refused (ARC-TPL-110) if the file changed "
                "since. Omit to skip the check."
            ),
        ] = None,
    ) -> PatchTemplateResult:
        """Apply path-addressed set/remove/insert ops to a template file (comment-preserving).

        Each op addresses a stable authored node id ('nodes.<id>[.<field>]') and names exactly
        one verb. One example per verb:

            {"set": "nodes.<id>.<field>", "value": <v>}          e.g. "nodes.title.style.fill"
            {"remove": "nodes.<id>[.<field>]"}                   a whole node, or one field
            {"insert_before": "nodes.<id>", "node": {...}}       a sibling before <id>
            {"insert_after": "nodes.<id>", "node": {...}}        a sibling after <id>

        A leaf field in a fixed-vocabulary block (style/fit/paragraph/constraints) is checked
        before writing, so a typo is a located diagnostic rather than a silent write. Pass the
        'sha256' from a prior inspect/patch as 'base_sha256' to reject a concurrent edit.
        """
        return self._facade.patch_template(Path(template), ops, base_sha256)

    # ---------------------------------------------------------------- projects
    def project_create(
        self,
        target: Annotated[
            str,
            Field(
                description=f"Directory to create the project in (created if absent); {_RELATIVE}."
            ),
        ],
        template: Annotated[
            str,
            Field(
                description="Template to pin: a library name ('<name>' or '<name>@<version>', "
                f"after arcavex_template_publish) or a template path ({_RELATIVE})."
            ),
        ],
        name: Annotated[
            str | None,
            Field(
                description="Project name written to project.yaml; defaults to the target "
                "directory's name."
            ),
        ] = None,
        style: Annotated[
            str | None,
            Field(
                description="Style pack name (arcavex_style_list) recorded in project.yaml."
            ),
        ] = None,
        formats: Annotated[
            list[str] | None,
            Field(
                description="Formats to render, from the template's declared formats; omit for "
                "all of them."
            ),
        ] = None,
        locales: Annotated[
            list[str] | None,
            Field(
                description="Locales to render, from the template's declared locales; omit for "
                "the source language alone."
            ),
        ] = None,
    ) -> ProjectResult:
        """Scaffold a project at 'target' pinning a template reference or path."""
        return self._facade.create_project(
            Path(target), name or Path(target).name, template,
            style=style, formats=formats, locales=locales,
        )

    def project_list(
        self,
        root: Annotated[
            str | None,
            Field(
                description="Directory to search (its own project.yaml and its immediate "
                f"children); {_RELATIVE}. Omit for the server's working directory."
            ),
        ] = None,
    ) -> ProjectListReport:
        """List projects discovered under 'root' (its own project.yaml and immediate children)."""
        return self._facade.list_projects(_opt_path(root))

    def project_status(self, project: _Project = None) -> ProjectStatusReport:
        """Report the active (or --project) project's manifest and recorded-run count."""
        return self._facade.project_status(project=_opt_path(project))

    def project_snapshot(self, project: _Project = None) -> ProjectSnapshotReport:
        """Open a project read-only and report its source and render revision manifests."""
        return self._facade.project_snapshot(project=_opt_path(project))

    def project_validate(
        self,
        project: _Project = None,
        formats: _Formats = None,
        locales: _Locales = None,
    ) -> CheckResult:
        """Validate the requested project targets without rendering or writing source files."""
        return self._facade.validate_project(
            project=_opt_path(project), formats=formats, locales=locales
        )

    def project_preview(
        self,
        project: _Project = None,
        formats: _Formats = None,
        locales: _Locales = None,
        dpi: Annotated[
            int | None,
            Field(
                description="Render DPI as an integer for every target, overriding each "
                "format's declared canvas dpi; omit for the declared dpi. 72 or 96 keeps the "
                "preview images small."
            ),
        ] = None,
    ) -> Annotated[CallToolResult, PreviewProjectReport]:
        """Preview every project target: the pictures as image content plus the structured report.

        The JSON block (the PreviewProjectReport: per-target ok, compile_ms, render_ms, dpi and
        pixel size, output_path, diagnostics) comes first and is also the structured content, so
        Arcavex Desktop's viewer keeps its contract; one image block follows for each target that
        rendered, so an assistant sees the previews instead of receiving cache paths it cannot
        open. A target that fails to compile has no image; its diagnostics say why.
        """
        report = self._facade.preview_project(
            project=_opt_path(project), formats=formats, locales=locales, dpi=dpi
        )
        content: list[ContentBlock] = [
            TextContent(type="text", text=report.model_dump_json(indent=2))
        ]
        for preview in report.previews:
            if preview.ok and preview.output_path:
                content.append(Image(path=preview.output_path).to_image_content())
        return CallToolResult(
            content=content, structuredContent=report.model_dump(mode="json"), isError=False
        )

    def layer_tree(
        self,
        project: _Project = None,
        mode: Annotated[
            Literal["authored", "rendered"],
            Field(
                description="'authored' returns the template's node hierarchy as written; "
                "'rendered' the resolved hierarchy after layout for the target."
            ),
        ] = "authored",
        format: _TargetFormat = None,
        locale: _Locale = None,
    ) -> LayerTreeReport:
        """Return the engine-owned definition or rendered hierarchy for one project target."""
        return self._facade.layer_tree(
            project=_opt_path(project), mode=mode, format_name=format, locale=locale
        )

    # ---------------------------------------------------------------- semantic editor
    def editor_apply(
        self,
        transaction: Annotated[
            dict[str, Any],
            Field(
                description="The semantic transaction object this tool's description shows "
                "(command_id, project_path, base_project_revision, actor, commands). Submit {} "
                "to have the engine restate the shape."
            ),
        ],
    ) -> TransactionReport:
        """Execute one semantic editor transaction; refusals return conflicts or diagnostics.

        A transaction is:

            {"command_id": "<uuid4>",
             "project_path": "<absolute path to the project directory>",
             "base_project_revision": "<project_revision from project_snapshot>",
             "actor": {"id": "<who is editing>"},
             "target": {"format": "<name>", "locale": "<name or null>"},   # optional
             "commands": [{"kind": "<one of the kinds below>", ...}]}

        All geometry is in points (``_pt``), whatever units the template is authored in. Command
        shapes, with their required fields:

            set_text          layer_id, text
            set_property      layer_id, keypath, value            (or remove: true)
            set_visibility    layer_id, visible
            set_display_name  layer_id, display_name              (writes project.ui.yaml)
            translate         layer_ids, dx_pt, dy_pt
            resize            layer_id, w_pt and/or h_pt
            rotate            layer_id, deg
            reorder           layer_id, parent_id, index
            reparent          layer_id, parent_id, index
            duplicate         layer_id
            delete            layer_ids
            group             layer_ids, group_id
            splice_children   layer_id, children
            set_effects       layer_id, effects

        The whole transaction applies or none of it does. A stale ``base_project_revision`` is
        refused as a conflict naming the files that moved; submit an empty transaction to have
        the engine restate this shape.
        """
        return self._facade.editor_apply(transaction)

    def editor_apply_authorized(
        self,
        project: Annotated[
            str,
            Field(description=f"Project directory (the one holding project.yaml); {_RELATIVE}."),
        ],
        command_id: Annotated[
            str,
            Field(
                description="The command_id of a proposal approved via project_proposal_approve."
            ),
        ],
    ) -> TransactionReport:
        """Execute an authorized proposal under a fresh revision check."""
        return self._facade.editor_apply_authorized(Path(project), command_id)

    def editor_undo(self, project: _ProjectOrCwd = None) -> TransactionReport:
        """Restore the project state before its newest applied history entry."""
        return self._facade.editor_undo(_opt_path(project) or Path.cwd())

    def editor_redo(self, project: _ProjectOrCwd = None) -> TransactionReport:
        """Re-apply the oldest undone history entry."""
        return self._facade.editor_redo(_opt_path(project) or Path.cwd())

    def editor_history(self, project: _ProjectOrCwd = None) -> HistoryReport:
        """Report the project's undo/redo timeline and whether an external edit branched it."""
        return self._facade.editor_history(_opt_path(project) or Path.cwd())

    def hit_test(
        self,
        x_pt: Annotated[
            float | str,
            Field(
                description="Horizontal canvas coordinate in points (pt) from the left edge; a "
                "number, or a numeric string."
            ),
        ],
        y_pt: Annotated[
            float | str,
            Field(
                description="Vertical canvas coordinate in points (pt) from the top edge; a "
                "number, or a numeric string."
            ),
        ],
        project: _Project = None,
        format: _TargetFormat = None,
        locale: _Locale = None,
    ) -> HitTestReport:
        """Return topmost-first rendered candidates containing one canvas point coordinate."""
        return self._facade.hit_test(
            project=_opt_path(project),
            x_pt=x_pt,
            y_pt=y_pt,
            format_name=format,
            locale=locale,
        )

    def project_ui_metadata(self, project: _Project = None) -> ProjectUIMetadataReport:
        """Read project-owned non-rendering layer and workspace metadata."""
        return self._facade.project_ui_metadata(project=_opt_path(project))

    def project_ui_metadata_set(
        self,
        metadata: Annotated[
            ProjectUIMetadata,
            Field(
                description="The complete project.ui.yaml content to write (per-layer display "
                "names and colors, workspace state); it replaces the whole file."
            ),
        ],
        project: _Project = None,
    ) -> ProjectUIMetadataReport:
        """Atomically replace validated project-owned editor metadata."""
        return self._facade.set_project_ui_metadata(
            metadata, project=_opt_path(project)
        )

    def project_policy(self, project: _Project = None) -> ProjectPolicyReport:
        """Return effective project automation and extension policy."""
        return self._facade.project_policy(project=_opt_path(project))

    def project_policy_set(
        self,
        mode: Annotated[
            AutomationMode,
            Field(
                description="Automation policy: 'unrestricted' applies agent transactions "
                "directly, 'review' records them as proposals for a person to approve, "
                "'read_only' refuses writes."
            ),
        ],
        extensions: Annotated[
            ExtensionMode,
            Field(
                description="'unrestricted' loads the project's extensions; 'disabled' renders "
                "with built-in components only."
            ),
        ],
        project: _Project = None,
    ) -> ProjectPolicyReport:
        """Atomically set project automation and extension policy."""
        return self._facade.set_project_policy(
            mode, extensions, project=_opt_path(project)
        )

    def project_proposal_list(self, project: _Project = None) -> ProposalListReport:
        """List deterministic proposal records and malformed-entry diagnostics."""
        return self._facade.list_project_proposals(project=_opt_path(project))

    def project_proposal_approve(
        self, command_id: _CommandId, project: _Project = None
    ) -> ProposalActionReport:
        """Authorize a current proposal without claiming its command was applied."""
        return self._facade.approve_project_proposal(
            command_id, project=_opt_path(project)
        )

    def project_proposal_reject(
        self,
        command_id: _CommandId,
        reason: Annotated[
            str, Field(description="Why the proposal is rejected; recorded with it.")
        ],
        project: _Project = None,
    ) -> ProposalActionReport:
        """Persist an explicit proposal rejection without deleting its record."""
        return self._facade.reject_project_proposal(
            command_id, reason, project=_opt_path(project)
        )

    def project_clone(
        self,
        target: Annotated[
            str,
            Field(
                description=f"Directory to create the clone in (created if absent); {_RELATIVE}."
            ),
        ],
        name: Annotated[
            str | None,
            Field(
                description="Name for the cloned project; defaults to the target directory's name."
            ),
        ] = None,
        project: Annotated[
            str | None,
            Field(
                description=f"Project to clone (the directory holding project.yaml); {_RELATIVE}. "
                "Omit to use the project found by walking up from the server's working directory."
            ),
        ] = None,
    ) -> ProjectResult:
        """Clone the active (or 'project') project into 'target', reset to draft."""
        return self._facade.clone_project(
            Path(target), name or Path(target).name, project=_opt_path(project),
        )

    def project_render(
        self,
        project: _Project = None,
        formats: _Formats = None,
        locales: _Locales = None,
        dpi: Annotated[
            int | dict[str, int] | None,
            Field(
                description="Render DPI: an integer applies to every format; a table "
                "{'<format>': <dpi>} sets each format separately (a format it omits keeps the "
                "default). Omit to render each format at its own declared canvas dpi, unless "
                "project.yaml, ARCAVEX_DPI, or config.toml set one."
            ),
        ] = None,
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
        template: _Template,
        data: _Data = None,
        format: _Format = None,
        locale: _Locale = None,
        style: _Style = None,
        dpi: _Dpi = None,
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
        self,
        keypath: Annotated[
            str,
            Field(
                description="Dotted path into the project's data, e.g. 'title' or "
                "'event.date'; every intermediate segment must be a mapping."
            ),
        ],
        value: Annotated[
            Any,
            Field(
                description="The value to write: a string, number, boolean, list, or mapping "
                "(a JSON value, not YAML text)."
            ),
        ],
        project: _Project = None,
    ) -> DataReport:
        """Set a single value at a dotted 'keypath' in the project's data, then revalidate."""
        return self._facade.set_data(keypath, value, project=_opt_path(project))

    def data_import(
        self,
        yaml_text: Annotated[
            str,
            Field(
                description="A YAML document of variable values, merged over the project's "
                "existing data (overlay: new keys are added, existing keys replaced)."
            ),
        ],
        locale: Annotated[
            str | None,
            Field(
                description="Write into this locale's data overlay instead of the base data; a "
                "locale the template declares."
            ),
        ] = None,
        project: _Project = None,
    ) -> DataReport:
        """Merge a YAML data document into the project's data (overlay semantics), then validate."""
        return self._facade.import_data(yaml_text, locale=locale, project=_opt_path(project))

    def asset_add(
        self,
        source: Annotated[
            str,
            Field(description=f"Image file to ingest (PNG, JPEG, WebP, …); {_RELATIVE}."),
        ],
        project: _Project = None,
    ) -> AssetReport:
        """Ingest an image into the workspace content-addressed store and return its reference."""
        return self._facade.add_asset(Path(source), project=_opt_path(project))

    def asset_annotate(
        self,
        sha256: Annotated[
            str, Field(description="The asset's content hash as returned by arcavex_asset_add.")
        ],
        annotations: Annotated[
            dict[str, Any],
            Field(
                description="Sidecar annotations to write, e.g. {'facing': 'left', "
                "'focal_point': [0.5, 0.3], 'tags': ['hero']}; focal_point is a fraction of "
                "width and height."
            ),
        ],
    ) -> AssetReport:
        """Write sidecar annotations (facing/focal_point/tags) onto an ingested asset."""
        return self._facade.annotate_asset(sha256, annotations)

    # ---------------------------------------------------------------- catalogs
    def style_list(self) -> StyleListReport:
        """List every installed style pack (palettes, fonts, effect presets, role defaults)."""
        return self._facade.list_styles()

    def style_inspect(
        self,
        name: Annotated[str, Field(description="Style pack name from arcavex_style_list.")],
    ) -> StyleInspectReport:
        """Report one style pack's palettes, fonts, effect presets, and role defaults."""
        return self._facade.inspect_style(name)

    def effects_list(self) -> EffectListReport:
        """List every registered effect, its category, and each param's type/default/range."""
        return self._facade.list_effects()

    def shape_list(self) -> ShapeListReport:
        """List every shape generator a shape node's 'generator:' may name, with its params.

        Each entry carries the generator's description and each param's type, default (or
        'required'), and range — the schema an ARC-FX-912 refusal validates against.
        """
        return self._facade.list_shapes()

    def font_list(self) -> FontListReport:
        """List every font family a template may name, marking bundled vs locally installed.

        Every family listed is 'available': rendering is confined to these families (there is
        no system-font fallback, for determinism), so this is the legal vocabulary for
        'style.font' — naming anything else is ARC-RND-010. 'source' says where a family comes
        from ('bundled' ships with the engine; 'installed' lives in the Arcavex home's fonts
        directory); file paths are informational, never something to copy. Installing a font is
        a local operator action, not an agent one: ask the user to run
        'arcavex font add <path/to/font.ttf>'.
        """
        return self._facade.list_fonts()

    # ---------------------------------------------------------------- render & inspect
    def render_preview(
        self,
        template: _Template,
        data: _Data = None,
        format: _Format = None,
        locale: _Locale = None,
        style: _Style = None,
        dpi: Annotated[
            int | None,
            Field(
                description="Render DPI as an integer, overriding the format's declared canvas "
                "dpi; pass 96 while iterating so the image stays small, omit for the declared "
                "dpi."
            ),
        ] = None,
        debug: _Debug = False,
        max_px: Annotated[
            int | None,
            Field(
                ge=1,
                description="Longest image side in pixels: when set, the dpi is lowered so "
                "neither side exceeds it (never raised); the JSON block reports the dpi and "
                "pixel size used. Use it to iterate on a large format without a 4000-pixel "
                "image on every call.",
            ),
        ] = None,
    ) -> list[Image | TextContent]:
        """Render a template to a preview PNG and return the image plus structured diagnostics.

        Returns MCP image content directly (base64 PNG) so the agent sees the render, followed by
        a JSON block carrying the structured PreviewResult (ok, timings, dpi and pixel size,
        diagnostics, path). With debug=true the image carries the layout overlay (node ids,
        bounds, baselines, anchors). On a compile/layout failure no image is produced; the
        PreviewResult block explains why.
        """
        result: PreviewResult = self._facade.render_preview(
            Path(template),
            _opt_path(data),
            format,
            locale=locale,
            style=style,
            dpi=dpi,
            debug=debug,
            max_px=max_px,
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
        template: _Template,
        data: _Data = None,
        format: _Format = None,
        locale: _Locale = None,
        style: _Style = None,
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
        template: _Template,
        data: _Data = None,
        format: _Format = None,
        locale: _Locale = None,
        style: _Style = None,
        output: Annotated[
            str | None,
            Field(
                description=f"Output file path ({_RELATIVE}); the extension selects the exporter "
                "(.png, .jpg, .jpeg, .webp, .pdf). Omit for the engine's default name, "
                "'<template stem>.<format>.png', reported under 'inferred'."
            ),
        ] = None,
        dpi: _Dpi = None,
        debug: _Debug = False,
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
        self,
        project: _Project = None,
        path: Annotated[
            str | None,
            Field(
                description="An outputs directory (or one run directory) to list instead of the "
                f"project's outputs/; {_RELATIVE}."
            ),
        ] = None,
    ) -> RunListReport:
        """List recorded runs for the active (or --project) project, or under an outputs 'path'."""
        return self._facade.list_runs(project=_opt_path(project), path=_opt_path(path))

    def run_diff(
        self,
        run_a: Annotated[
            str,
            Field(
                description="Run directory of the first run (the 'run_dir' a render result or "
                f"arcavex_run_list reports); {_RELATIVE}."
            ),
        ],
        run_b: Annotated[
            str, Field(description=f"Run directory of the second run; {_RELATIVE}.")
        ],
    ) -> DiffReport:
        """Diff two recorded runs: per-output pixels/perceptual plus provenance metadata."""
        return self._facade.diff_runs(Path(run_a), Path(run_b))

    def run_rerun(
        self,
        run_dir: Annotated[
            str | None,
            Field(
                description="Run directory to reproduce (the 'run_dir' a render result reports); "
                f"{_RELATIVE}."
            ),
        ] = None,
        run_id: Annotated[
            str | None,
            Field(
                description="Alternatively, the 'run_id' that arcavex_run_list reports; resolved "
                "under the project's outputs/ directory."
            ),
        ] = None,
        project: Annotated[
            str | None,
            Field(
                description="Project whose outputs/ holds 'run_id' (the directory holding "
                f"project.yaml); {_RELATIVE}. Omit for the server's working directory."
            ),
        ] = None,
    ) -> RerunReport:
        """Reproduce a recorded run into a new run directory (byte-identical on match).

        Takes either the run directory or the ``run_id`` that ``arcavex_run_list`` reports —
        listing runs and then rerunning one should not require knowing that the id happens to be
        the directory's name under ``outputs/``.
        """
        if run_dir is not None:
            return self._facade.rerun(Path(run_dir))
        if run_id is None:
            return RerunReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-RUN-001",
                        "Pass either 'run_dir' or the 'run_id' that arcavex_run_list reports.",
                        hint="arcavex_run_list returns run_id for every recorded run.",
                    )
                ],
            )
        listed = self._facade.list_runs(project=_opt_path(project), path=None)
        match = next((run for run in listed.runs if run.run_id == run_id), None)
        if match is None:
            known = ", ".join(run.run_id for run in listed.runs[:5]) or "none recorded"
            return RerunReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-RUN-001",
                        f"No recorded run {run_id!r} for this project.",
                        hint=f"Recorded runs: {known}.",
                    )
                ],
            )
        root = Path(project) if project else Path.cwd()
        return self._facade.rerun(root / "outputs" / match.run_id)

    # ---------------------------------------------------------------- diagnostics
    def diagnostic_explain(
        self,
        code: Annotated[
            str,
            Field(description="A diagnostic code such as 'ARC-TPL-014' (case-insensitive)."),
        ],
    ) -> DiagnosticHelp:
        """Explain a diagnostic code: what it means and the typical fix."""
        return self._facade.explain_diagnostic(code)


# The tool catalog: MCP tool name -> the ArcavexTools method it wraps. One registration site so
# the catalog, the server, and the tests all read from a single source of truth.
_TOOL_METHODS: tuple[tuple[str, str], ...] = (
    ("engine_handshake", "engine_handshake"),
    ("arcavex_template_list", "template_list"),
    ("arcavex_template_inspect", "template_inspect"),
    ("arcavex_template_new", "template_new"),
    ("arcavex_template_publish", "template_publish"),
    ("arcavex_template_detach", "template_detach"),
    ("arcavex_template_validate", "template_validate"),
    ("arcavex_template_patch", "template_patch"),
    ("arcavex_project_create", "project_create"),
    ("arcavex_project_list", "project_list"),
    ("arcavex_project_status", "project_status"),
    ("project_snapshot", "project_snapshot"),
    ("project_validate", "project_validate"),
    ("project_preview", "project_preview"),
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
    ("arcavex_shape_list", "shape_list"),
    ("arcavex_font_list", "font_list"),
    ("arcavex_render_preview", "render_preview"),
    ("arcavex_layout_inspect", "layout_inspect"),
    ("arcavex_render", "render"),
    ("arcavex_run_list", "run_list"),
    ("arcavex_run_diff", "run_diff"),
    ("arcavex_run_rerun", "run_rerun"),
    ("arcavex_diagnostic_explain", "diagnostic_explain"),
    ("arcavex_editor_apply", "editor_apply"),
    ("arcavex_editor_apply_authorized", "editor_apply_authorized"),
    ("arcavex_editor_undo", "editor_undo"),
    ("arcavex_editor_redo", "editor_redo"),
    ("arcavex_editor_history", "editor_history"),
)


# ------------------------------------------------------------------- the argument contract
class _ArcavexServer(FastMCP):
    """FastMCP with the engine's argument contract in front of dispatch.

    The SDK validates arguments inside ``Tool.run`` and reports a failure as pydantic's own text
    wrapped in "Error executing tool …" — the one place an assistant met prose instead of a
    coded diagnostic. Checking here, before dispatch, makes a refusal the same envelope every
    other refusal is, and guarantees nothing runs on arguments the tool did not declare.
    """

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Refuse malformed arguments with a coded envelope; otherwise dispatch as the SDK does."""
        tool = self._tool_manager.get_tool(name)
        if tool is not None:
            refusal = _refuse_bad_arguments(tool, arguments)
            if refusal is not None:
                return refusal
        return await super().call_tool(name, arguments)


def _harden_tool(tool: Tool) -> None:
    """Make one registered tool refuse unknown argument keys, in its schema and at call time.

    The SDK builds the argument model with pydantic's default of ignoring unknown keys, so
    ``arcavex_template_new {format: ...}`` answered ok:true and the assistant believed the option
    took effect. A subclass with ``extra='forbid'`` is the smallest change that makes the
    published inputSchema (``additionalProperties: false``, so a well-behaved client refuses
    locally) and the server-side check agree.
    """
    arg_model = tool.fn_metadata.arg_model
    strict = type(arg_model.__name__, (arg_model,), {"model_config": ConfigDict(extra="forbid")})
    tool.fn_metadata.arg_model = strict
    tool.parameters = strict.model_json_schema(by_alias=True)


def _refuse_bad_arguments(tool: Tool, arguments: dict[str, Any]) -> CallToolResult | None:
    """Return the coded refusal for unknown, missing, or mistyped arguments; ``None`` if valid.

    The same pre-parse the SDK applies runs first (Claude Desktop sends a list as its JSON text),
    so a caller the SDK would have accepted is never refused here. Every problem in the call is
    reported at once: one round trip per defect was the audit's whole cost.
    """
    metadata = tool.fn_metadata
    try:
        metadata.arg_model.model_validate(metadata.pre_parse_json(arguments))
    except ValidationError as exc:
        diagnostics = [_argument_diagnostic(tool, error) for error in exc.errors()]
    else:
        return None
    envelope: dict[str, Any] = {
        "ok": False,
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
    }
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(envelope, ensure_ascii=False, indent=2))
        ],
        structuredContent=envelope,
        isError=True,
    )


def _argument_diagnostic(tool: Tool, error: Mapping[str, Any]) -> Diagnostic:
    """Translate one pydantic error on a tool's arguments into a coded, located diagnostic."""
    properties: dict[str, Any] = tool.parameters.get("properties", {})
    location = tuple(str(part) for part in error.get("loc") or ())
    field = location[0] if location else "(arguments)"
    kind = error.get("type")
    if kind == "extra_forbidden":
        close = difflib.get_close_matches(field, list(properties), n=1, cutoff=0.6)
        suggestion = f" Did you mean {close[0]!r}?" if close else ""
        return diagnostic(
            "ARC-MCP-010",
            f"Unknown argument {field!r} for tool {tool.name}; the call was refused rather than "
            "run without it.",
            keypath=field,
            hint=f"{tool.name} accepts: {', '.join(properties) or 'no arguments'}.{suggestion}",
        )
    if kind == "missing":
        return diagnostic(
            "ARC-MCP-011",
            f"Missing required argument {field!r} for tool {tool.name}.",
            keypath=field,
            hint=_argument_guide(tool.parameters),
        )
    schema = properties.get(field, {})
    description = str(schema.get("description") or "no description").rstrip(".")
    return diagnostic(
        "ARC-MCP-012",
        f"Invalid value for argument {field!r} of tool {tool.name}: {error.get('msg')}.",
        keypath=".".join(location) or None,
        hint=f"{field}: {description}. Expects {_expected(schema)}.",
    )


def _argument_guide(parameters: Mapping[str, Any]) -> str:
    """One entry per argument, required first, each with its meaning: the tool's own manual."""
    properties: dict[str, Any] = parameters.get("properties", {})
    required = set(parameters.get("required", ()))

    def describe(name: str) -> str:
        description = str(properties[name].get("description") or "").rstrip(".")
        return f"{name} ({description})" if description else name

    mandatory = "; ".join(describe(n) for n in properties if n in required) or "none"
    optional = "; ".join(describe(n) for n in properties if n not in required)
    guide = f"Required: {mandatory}."
    if optional:
        guide += f" Optional: {optional}."
    return guide


def _expected(schema: Mapping[str, Any]) -> str:
    """Say what a JSON schema fragment accepts, in words an assistant can act on."""
    if "enum" in schema:
        return "one of " + ", ".join(repr(value) for value in schema["enum"])
    if "anyOf" in schema:
        return " or ".join(_expected(option) for option in schema["anyOf"])
    if "$ref" in schema:
        return f"a {str(schema['$ref']).rsplit('/', 1)[-1]} object"
    kind = schema.get("type")
    if kind == "array":
        return f"an array of {_expected(schema.get('items', {}))}"
    return str(kind) if kind else "a JSON value"


def build_mcp_server(facade: Facade | None = None) -> FastMCP:
    """Build the FastMCP server, registering every tool over a (possibly injected) facade.

    A caller may inject a facade (tests, or a host that already built one); otherwise one is
    built via :func:`~arcavex.bootstrap.build_facade`, exactly as the CLI does. ``render_preview``
    opts out of structured output because it returns mixed image + text content;
    ``project_preview`` returns a ``CallToolResult`` carrying both the images and the structured
    report, and keeps the report's output schema. Every tool is then hardened against unknown
    argument keys (see :func:`_harden_tool`).
    """
    tools = ArcavexTools(facade if facade is not None else build_facade())
    with _without_the_sdks_settings_warning():
        server = _ArcavexServer("arcavex", instructions=_INSTRUCTIONS)
    # FastMCP has no version parameter, so the handshake would advertise the MCP SDK's version as
    # the server's. A client pinning the engine it talks to needs the engine's own.
    server._mcp_server.version = __version__  # noqa: SLF001
    for tool_name, method_name in _TOOL_METHODS:
        method = getattr(tools, method_name)
        structured = None if method_name != "render_preview" else False
        server.tool(name=tool_name, structured_output=structured)(method)
        registered = server._tool_manager.get_tool(tool_name)  # noqa: SLF001
        assert registered is not None, tool_name
        _harden_tool(registered)
    _register_skill_resources(server, tools._facade)
    return server


def _register_skill_resources(server: FastMCP, facade: Facade) -> None:
    """Serve the bundled design skill so a client can learn this engine from this engine.

    ``arcavex skill install`` copies the skill into Claude Code's or Codex's own skill directory,
    which helps those hosts and only when a person runs the command. Every other client — the ones
    this server exists for — had no way to discover that the document exists, so an assistant's
    only route to the template grammar was to provoke validation errors until they enumerated it.

    The files are read at call time rather than at build time: the skill is documentation, and a
    server should not hold a stale copy of it in memory for the life of the process.
    """
    from mcp.server.fastmcp.resources import FunctionResource
    from pydantic import AnyUrl

    # Asked through the facade rather than the skill service: a client may only speak to the
    # engine's public API, and "where does your skill live" is a fair question to ask it.
    listed = facade.list_skill_targets()
    if not listed.source:  # pragma: no cover - a build without the bundled skill
        return
    root = Path(listed.source)
    if not (root / "SKILL.md").is_file():  # pragma: no cover - defensive
        return
    skill_name = listed.skill or root.name

    documents = [root / "SKILL.md", *sorted((root / "references").glob("*.md"))]
    for document in documents:
        relative = document.relative_to(root).as_posix()
        server.add_resource(
            FunctionResource(
                uri=AnyUrl(f"skill://{skill_name}/{relative}"),
                name=relative,
                description=(
                    "The Arcavex design skill: how to drive this engine as a designer."
                    if relative == "SKILL.md"
                    else f"Arcavex design skill reference: {document.stem}."
                ),
                mime_type="text/markdown",
                fn=lambda path=document: path.read_text(encoding="utf-8"),
            )
        )


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

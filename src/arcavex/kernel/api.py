"""The service API facade — the one front door above the kernel.

Clients (CLI, MCP, Python) call this facade and never reach into services or built-ins
directly. The facade orchestrates the pipeline (compile -> layout -> render -> export)
using dependencies injected by :mod:`arcavex.bootstrap`, so the kernel imports nothing from
services or built-ins. No raw exception ever leaves this module: unexpected errors are
wrapped as ``ARC-INT-999`` diagnostics.
"""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import UUID4, BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from arcavex.kernel.contracts.types import (
    ExportOptions,
    MeasureFn,
)
from arcavex.kernel.diagnostics import (
    Diagnostic,
    DiagnosticError,
    diagnostic,
    has_errors,
    internal_error,
)
from arcavex.kernel.editor import (
    Actor,
    EditorProtocol,
    HistoryReport,
    TransactionReport,
)
from arcavex.kernel.ir.models import (
    CompiledDocument,
    CompiledGroup,
    CompiledImage,
    CompiledNode,
    LayoutDocument,
    LayoutNode,
    ResolvedShape,
    ResolvedText,
    SourceRef,
)
from arcavex.kernel.ir.units import GEOMETRY_QUANTUM_PT, Matrix3, Rect
from arcavex.kernel.pipeline import layout_and_render
from arcavex.kernel.registry import Registries

_EXPORTER_BY_EXT: dict[str, str] = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".pdf": "pdf",
}

# Default lossy-encoder quality when ``--quality`` is omitted (JPEG, lossy WebP). 90 is the
# conventional "visually lossless, small" setting; the previous 100 produced JPEGs larger than
# the equivalent PNG with no visible gain (DX-4). PNG/PDF ignore it; lossless WebP overrides it.
_DEFAULT_EXPORT_QUALITY = 90

# Machine-readable responses carry this so consumers key on a version, not a shape.
RESPONSE_VERSION = 1

# ---------------------------------------------------------------- layout-inspection constants
#
# Tolerance for comparing resolved coordinates. The solver rounds geometry to
# GEOMETRY_QUANTUM_PT, so an exact edge test would turn on the last bit of an accumulated
# coordinate; ten quanta is far above that noise and still 0.0098pt — 1/7000 inch, under a
# hundredth of a pixel at 300 dpi, so no intersection a reader could see is discarded by it.
_GEOMETRY_EPS_PT = 10 * GEOMETRY_QUANTUM_PT

# A leaf covering at least this fraction of its parent region is treated as a background, so
# enclosing a sibling is layering rather than a collision. Area is the only signal available
# here: nothing in the IR declares intent, and a node's own paint order says nothing about
# whether it is a backdrop for a *sibling*. It therefore misjudges the edges in both directions —
# a thin diagonal strip spanning the region qualifies, a true background at 0.88 does not. An
# explicit authoring flag would replace it; see docs/backlog.md.
_BACKDROP_AREA_FRACTION = 0.9

# An intersection no deeper than this on its short side, or smaller than this fraction of the
# smaller of the two boxes, is a graze and is reported as ``touch`` rather than ``content``. One
# point is where a correction stops being visible: 1.3px at 96 dpi, inside the anti-aliased edge a
# rasterizer draws anyway. Two percent of the smaller box's area is the corner-nick regime — along
# a full edge it is a sliver 2% of that box's depth, at a corner an overlap of ~14% of each side —
# a nudge, not a re-layout. Both are measured on the collision boxes (``_collision_rect``): a text
# node's line box is taller than its glyphs, so a graze that only reaches a font's leading still
# counts by the leading's full depth.
_TOUCH_MAX_DEPTH_PT = 1.0
_TOUCH_MAX_AREA_FRACTION = 0.02

# Resolution of the canvas-coverage grid used by `covered_fraction` and `free_regions`. 64x64
# over the shortest supported canvas edge is a cell of a few points, fine enough to locate an
# empty slab and coarse enough to stay O(1) per node. Coverage is therefore an approximation
# biased upward: a node smaller than one cell still marks the whole cell.
_COVERAGE_GRID_CELLS = 64

# Reported precision of `covered_fraction`. The grid resolves 1/4096 of the canvas, so four
# decimals report every distinguishable value and no more.
_COVERAGE_DECIMALS = 4

# Shortest run of empty grid rows reported as a free region: one row is a sliver at the
# resolution of the grid rather than usable space.
_MIN_FREE_BAND_ROWS = 2

# A project/provenance result model — every one carries ``ok`` and ``diagnostics``, so the
# facade's never-raises boundary helper is generic over the concrete report it returns.
_ResultT = TypeVar("_ResultT", bound="BaseModel")
_FinitePoint = tuple[FiniteFloat, FiniteFloat]
_FiniteRect = tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
_FiniteMatrix = tuple[
    FiniteFloat,
    FiniteFloat,
    FiniteFloat,
    FiniteFloat,
    FiniteFloat,
    FiniteFloat,
]


def _preview_variant(
    data: Path | None, locale: str | None, dpi: int | None, style: str | None
) -> str:
    """Spell out the preview inputs beyond template + format that change the rendered pixels.

    Empty when none is given, which is what keeps the plain preview path historical. Each part is
    tagged with its name so a locale that happens to spell like a style reference, or a style file
    that happens to equal a data path, cannot fold to the same key. The data path is resolved so
    ``./data.yaml`` and its absolute spelling share one preview.
    """
    parts: list[str] = []
    if data is not None:
        parts.append(f"data={Path(data).resolve()}")
    if locale is not None:
        parts.append(f"locale={locale}")
    if dpi is not None:
        parts.append(f"dpi={dpi}")
    if style is not None:
        parts.append(f"style={style}")
    return "\n".join(parts)


def _output_name(stem: str, fmt: str, locale: str | None) -> str:
    """Build the default output filename ``<stem>.<format>[.<locale>].png`` (§6.3 / DX-3)."""
    locale_seg = f".{locale}" if locale else ""
    return f"{stem}.{fmt}{locale_seg}.png"


def _hit_point(x_pt: float | str, y_pt: float | str) -> tuple[float, float]:
    """Coerce one finite point or raise the stable public input diagnostic."""
    try:
        point = (float(x_pt), float(y_pt))
    except (TypeError, ValueError, OverflowError) as exc:
        raise DiagnosticError(
            diagnostic(
                "ARC-IR-015",
                "Hit-test coordinates must be finite numbers",
                keypath="point_pt",
                hint=(
                    "Pass numeric canvas-point x_pt and y_pt values; "
                    "NaN and infinity are invalid."
                ),
            )
        ) from exc
    if not all(math.isfinite(value) for value in point):
        raise DiagnosticError(
            diagnostic(
                "ARC-IR-015",
                "Hit-test coordinates must be finite numbers",
                keypath="point_pt",
                hint=(
                    "Pass numeric canvas-point x_pt and y_pt values; "
                    "NaN and infinity are invalid."
                ),
            )
        )
    return point


def _dedupe(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Remove duplicate diagnostics while preserving first-seen order."""
    seen: set[tuple[object, ...]] = set()
    out: list[Diagnostic] = []
    for diag in diagnostics:
        src = diag.source
        key = (
            diag.code,
            diag.message,
            None if src is None else (src.file, src.keypath, src.line),
        )
        if key not in seen:
            seen.add(key)
            out.append(diag)
    return out


@dataclass
class CompileResult:
    """The output of compilation: a document (on success) and diagnostics.

    ``inferred`` records unambiguous choices the compiler made on the caller's behalf
    (e.g. ``{"format": "square", "data": "preview_data"}``) so clients can report them
    (§6.3). ``format_name`` is the format actually compiled, used for default output naming.
    """

    document: CompiledDocument | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    inferred: dict[str, str] = field(default_factory=dict)
    format_name: str | None = None
    # Provenance (§5.3): the fully-resolved variable snapshot and canonical input hashes,
    # populated on a successful compile. ``resolved_data`` is the merged variable context
    # (defaults, overlays, and locale data applied) with derived injections like ``palette``
    # stripped, so a rerun can reconstruct the exact document from it. The hashes are the
    # canonical SHA-256 digests of the template source, the applied style pack, and the
    # resolved data — the inputs a manifest records and a diff compares.
    resolved_data: dict[str, Any] | None = None
    template_hash: str | None = None
    style_hash: str | None = None
    data_hash: str | None = None
    # Effective authored AST after target/project structural patches but before if/repeat
    # expansion. The source map is keyed by ``id(node_mapping)`` so duplicate authored IDs do
    # not erase provenance before validation. Both are process-local compiler/service contracts,
    # never serialized or included in canonical hashes.
    effective_root: Any | None = None
    effective_source_map: dict[int, SourceRef] = field(default_factory=dict)


@dataclass
class ProjectInputs:
    """The resolved compile inputs for a project's render targets (project-mode dry runs).

    Returned by the orchestrator so the facade can validate or preview a project's current
    template + data + override patch across its formats × locales without re-implementing
    project resolution — the same inputs ``render`` project mode uses (DX-1). ``patch_ops`` are
    the raw override ops (line info preserved for located ``ARC-TPL-092`` diagnostics), so this
    is a plain dataclass rather than a pydantic model that would flatten them.
    """

    name: str
    template_dir: Path
    ref: str
    is_library: bool
    style: str | None
    data_path: Path | None
    patch_ops: list[Any] | None
    patch_file: Path | None
    targets: list[tuple[str, str | None]]
    #: Project-level findings that hold for every target (e.g. ``ARC-PRJ-015`` placeholder copy
    #: still in the data file), reported once by validate/preview rather than per target.
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class ResolvedPatch:
    """One applied patch operation plus the value it produced (for --resolved)."""

    layer: str
    op: str
    path: str
    value: Any = None
    effective: bool = True


@dataclass
class ResolvedResult:
    """The compiler's provenance view for ``template inspect --resolved`` (CR-1)."""

    ok: bool
    format_name: str | None = None
    locale: str | None = None
    direction: str | None = None
    digits: str | None = None
    style: str | None = None
    patches: list[ResolvedPatch] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


class CompilerProtocol(Protocol):
    """The compiler dependency injected by bootstrap."""

    def compile(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        resolved_data: dict[str, Any] | None = None,
        project_patch: list[Any] | None = None,
        project_patch_file: Path | None = None,
    ) -> CompileResult:
        """Compile a template + data into a :class:`CompiledDocument`.

        When ``resolved_data`` is given (rerun), it is the authoritative variable snapshot: the
        data file, preview data, and locale data overlays are skipped and the snapshot is used
        directly, while template-level structural resolution (format/locale patches, direction,
        digits) still runs so the output is byte-identical to the original. ``project_patch`` is
        the project override layer applied after the format/locale patches (§5.4).
        """
        ...

    def inspect_resolved(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
    ) -> ResolvedResult:
        """Report the final layered values and their originating layers (--resolved)."""
        ...

    def list_formats(self, template: Path) -> list[str]:
        """Return the names of formats declared by a template (best effort)."""
        ...

    def resolve_paths(self, template: Path) -> tuple[Path, Path]:
        """Return ``(root_dir, template_yaml)`` for a template path (file or directory)."""
        ...


class StylePackProtocol(Protocol):
    """The structural view of a loaded style pack the facade reports on."""

    name: str
    version: str
    palettes: dict[str, list[str]]
    fonts: dict[str, list[str]]
    effect_presets: dict[str, dict[str, Any]]
    shape_presets: dict[str, dict[str, Any]]
    roles: dict[str, dict[str, Any]]


class StyleProviderProtocol(Protocol):
    """The style-resolver dependency injected by bootstrap (kept out of the pure kernel)."""

    def list_packs(self) -> list[StylePackProtocol]:
        """Return every discoverable style pack."""
        ...

    def inspect(self, ref: str) -> StylePackProtocol:
        """Load a style pack by ``name@version`` reference."""
        ...


class StyleSummary(BaseModel):
    """A style pack rendered for ``style list``/``inspect`` output (spec §3.7)."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    palettes: dict[str, list[str]] = Field(default_factory=dict)
    fonts: dict[str, list[str]] = Field(default_factory=dict)
    effect_presets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    shape_presets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    roles: dict[str, dict[str, Any]] = Field(default_factory=dict)


class StyleListReport(BaseModel):
    """The result of ``arcavex style list``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    styles: list[StyleSummary] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class StyleInspectReport(BaseModel):
    """The result of ``arcavex style inspect NAME``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    style: StyleSummary | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class EffectParamInfo(BaseModel):
    """One parameter of an effect's schema, as reported by ``effects list``/``effect inspect``."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    required: bool = False
    default: Any = None
    constraint: str | None = None


class EffectInfo(BaseModel):
    """A registered effect's name, category, and parameter schema (DX-6 discovery)."""

    model_config = ConfigDict(frozen=True)

    name: str
    category: str
    params: list[EffectParamInfo] = Field(default_factory=list)


class EffectListReport(BaseModel):
    """The result of ``arcavex effects list`` — every registered effect and its params."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    effects: list[EffectInfo] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ShapeInfo(BaseModel):
    """A registered shape generator (``generator:`` on a shape node) and its parameter schema.

    Parameters reuse :class:`EffectParamInfo`: a generator's ``params`` follow the same
    conventions as an effect's (a bare number is points, lengths take ``pt``/``mm``), so the
    discovery output reads the same way.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    params: list[EffectParamInfo] = Field(default_factory=list)


class ShapeListReport(BaseModel):
    """The result of ``arcavex shapes list`` — every registered shape generator and its params."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    shapes: list[ShapeInfo] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


# ----------------------------------------------------------------------------- fonts (§4.3)
class FontFileInfo(BaseModel):
    """One font file backing a family, and whether it came from the install directory."""

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    installed: bool


class FontFamilyInfo(BaseModel):
    """A resolvable font family: its files, and where they came from.

    ``bundled`` and ``installed`` are separate flags rather than one enum because they are not
    exclusive — installing an extra weight of a bundled family is legitimate, and a single
    "source" field would have to misreport that case.
    """

    model_config = ConfigDict(frozen=True)

    family: str
    bundled: bool
    installed: bool
    files: list[FontFileInfo] = Field(default_factory=list)


class FontListReport(BaseModel):
    """The result of ``arcavex font list`` — every family the shaper will resolve.

    ``install_dir`` names the directory ``font add`` writes to, so "where do I put a font?" is
    answered by the output rather than by prose buried in the docs.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    install_dir: str
    families: list[FontFamilyInfo] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class FontActionReport(BaseModel):
    """The result of ``arcavex font add`` / ``arcavex font remove``.

    ``family`` is the name the ENGINE resolves for the font — read from the file with the shaper's
    own resolver, never guessed from the filename — because that is the name a template must
    write in ``style.font``.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    family: str | None = None
    files: list[str] = Field(default_factory=list)
    license: str | None = None
    install_dir: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class SkillTargetInfo(BaseModel):
    """One destination `arcavex skill install` can write to.

    ``verified`` distinguishes a layout this project tests against from one taken from a vendor's
    documented configuration directory, which that vendor may move.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    path: str
    installed: bool
    verified: bool = False


class SkillInstallReport(BaseModel):
    """The result of ``arcavex skill install`` / ``--list``.

    ``targets`` describes every destination considered; ``installed`` lists the ones written this
    run, so a no-op (already present, no ``--force``) is distinguishable from a write.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    skill: str
    source: str
    targets: list[SkillTargetInfo] = Field(default_factory=list)
    installed: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class SkillServiceProtocol(Protocol):
    """The skill installer injected by bootstrap.

    Returns versioned kernel result models and does not raise across the facade boundary.
    """

    def list_targets(self, path: Path | None, *, project: bool) -> SkillInstallReport: ...

    def install(
        self,
        *,
        targets: list[str] | None,
        path: Path | None,
        force: bool,
        project: bool,
    ) -> SkillInstallReport: ...


class McpTargetInfo(BaseModel):
    """One AI host ``arcavex mcp install`` can register the MCP server with.

    ``location`` is where the registration lives — the config file this command edits, or the
    host CLI that owns it — and ``snippet`` is what a person would paste to make the same
    registration by hand, so ``--print`` and a host-not-found diagnostic can show the manual
    route. ``available`` says whether the host is present on this machine at all.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    location: str
    available: bool
    registered: bool
    snippet: str
    note: str | None = None


class McpInstallReport(BaseModel):
    """The result of ``arcavex mcp install`` / ``--list`` / ``--print``.

    ``command`` is the exact command line registered (or that would be) — absolute paths, so it
    works from any working directory the host starts it in. ``targets`` describes every host
    considered and ``installed`` names, by key, the ones written this run, so a no-op (already
    registered, no ``--force``) is distinguishable from a write.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    command: list[str] = Field(default_factory=list)
    targets: list[McpTargetInfo] = Field(default_factory=list)
    installed: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class McpHostServiceProtocol(Protocol):
    """The MCP host registrar injected by bootstrap.

    Returns versioned kernel result models and does not raise across the facade boundary.
    """

    def list_targets(self, *, command: Path | None) -> McpInstallReport: ...

    def install(
        self,
        *,
        targets: list[str] | None,
        command: Path | None,
        force: bool,
    ) -> McpInstallReport: ...


class FontServiceProtocol(Protocol):
    """The font install/inspect service injected by bootstrap (spec §4.3).

    Every method returns a versioned kernel result model and does not raise across the facade
    boundary. The concrete implementation lives in ``services.fonts`` and reads/writes the font
    store under the Arcavex home.
    """

    def list_fonts(self) -> FontListReport: ...

    def add_font(self, source: Path, license_path: Path | None) -> FontActionReport: ...

    def remove_font(self, family: str) -> FontActionReport: ...


class RenderResult(BaseModel):
    """The result of a render request.

    ``output_path`` is the absolute path of the written file: the CLI's ``--json`` and the MCP
    render tool are read by an assistant that may have run the command from another directory,
    where a path relative to the engine's working directory opens nothing. ``inferred["output"]``
    is different in kind — the default *name* the engine chose when no output was given,
    relative to the working directory exactly as the human ``inferred:`` line reports it.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    output_path: str | None
    diagnostics: list[Diagnostic]
    content_sha256: str | None = None
    inferred: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- doctor
class DoctorCheck(BaseModel):
    """One environment probe result in a doctor report."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: Literal["ok", "warn", "fail"]
    detail: str
    hint: str | None = None


class DoctorReport(BaseModel):
    """The result of ``arcavex doctor``: engine version plus per-probe check rows."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    engine_version: str
    checks: list[DoctorCheck]


# --------------------------------------------------------------------------- desktop
class EngineIdentity(BaseModel):
    """Release identity for the executable serving a desktop client."""

    model_config = ConfigDict(frozen=True)

    engine_version: str
    build_commit: str | None = None
    artifact_path: str | None = None
    artifact_sha256: str | None = None


class EnginePaths(BaseModel):
    """Arcavex home and the persistent stores rooted beneath it."""

    model_config = ConfigDict(frozen=True)

    home: str
    assets: str
    cache: str
    extensions: str
    fonts: str
    styles: str
    templates: str


class EngineHandshakeReport(BaseModel):
    """Versioned startup contract shared by desktop CLI and MCP clients."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    identity: EngineIdentity
    mcp_contract_version: str
    accepted_ir_versions: list[str]
    produced_ir_version: str
    extension_sdk_version: str
    capabilities: list[str]
    paths: EnginePaths
    doctor: DoctorReport
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class DesktopServiceProtocol(Protocol):
    """Desktop identity service injected by bootstrap to keep the kernel pure."""

    def handshake(self) -> EngineHandshakeReport: ...


class RevisionManifestEntry(BaseModel):
    """One normalized file or synthetic projection participating in a revision."""

    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    bytes: int


class ProjectTarget(BaseModel):
    """One deterministic format and locale combination declared by a project."""

    model_config = ConfigDict(frozen=True)

    format: str
    locale: str | None = None


class ProjectSourceFile(BaseModel):
    """A project input and its resolved source location for conflict diagnostics."""

    model_config = ConfigDict(frozen=True)

    path: str
    resolved_path: str
    role: Literal["project", "ui", "template", "data", "override", "asset"]
    project_owned: bool
    sha256: str | None = None


class ProjectSnapshotReport(BaseModel):
    """Read-only desktop snapshot with independent project and render revisions."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    canonical_path: str | None = None
    name: str | None = None
    template: str | None = None
    style: str | None = None
    data: str | None = None
    dpi: int | None = None
    formats: list[str] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=list)
    targets: list[ProjectTarget] = Field(default_factory=list)
    default_target: ProjectTarget | None = None
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    project_revision: str | None = None
    render_revision: str | None = None
    project_manifest: list[RevisionManifestEntry] = Field(default_factory=list)
    render_manifest: list[RevisionManifestEntry] = Field(default_factory=list)
    source_files: list[ProjectSourceFile] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class LayerUIMetadata(BaseModel):
    """Non-rendering editor metadata for one stable authored layer ID."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    display_name: str | None = None
    locked: bool = False
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ProjectWorkspaceState(BaseModel):
    """Project-local workspace choices that may travel with the authored project."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_format: str | None = None
    active_locale: str | None = None
    layer_tree_mode: Literal["definition", "rendered"] = "definition"
    selected_layer_ids: list[str] = Field(default_factory=list)


class ProjectUIMetadata(BaseModel):
    """Versioned contents of the optional non-rendering ``project.ui.yaml`` sidecar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    layers: dict[str, LayerUIMetadata] = Field(default_factory=dict)
    workspace: ProjectWorkspaceState = Field(default_factory=ProjectWorkspaceState)

    @field_validator("layers")
    @classmethod
    def _stable_layer_ids(
        cls, value: dict[str, LayerUIMetadata]
    ) -> dict[str, LayerUIMetadata]:
        if any(not layer_id.strip() for layer_id in value):
            raise ValueError("layer metadata keys must be non-empty stable authored IDs")
        return value


class ProjectUIMetadataReport(BaseModel):
    """Current editor metadata together with the revisions that govern it."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    canonical_path: str | None = None
    metadata: ProjectUIMetadata = Field(default_factory=ProjectUIMetadata)
    project_revision: str | None = None
    render_revision: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


AutomationMode = Literal["unrestricted", "review", "read_only"]
ExtensionMode = Literal["unrestricted", "disabled"]


class AutomationPolicy(BaseModel):
    """Versioned project-local policy for semantic automation and extension execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    mode: AutomationMode = "unrestricted"
    extensions: ExtensionMode = "unrestricted"


class ProjectPolicyReport(BaseModel):
    """Current project policy together with the revisions that govern it."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    canonical_path: str | None = None
    policy: AutomationPolicy = Field(default_factory=AutomationPolicy)
    project_revision: str | None = None
    render_revision: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


#: A queued proposal and an executed transaction name the same actor, so they share one model
#: rather than two identical ones that could drift apart.
ProposalActor = Actor


ProposalState = Literal["pending", "authorized", "rejected"]


class ProjectProposal(BaseModel):
    """Versioned queue record for a future semantic editor command."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    command_id: UUID4
    project_path: str
    base_project_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor: ProposalActor
    command_payload: dict[str, Any]
    created_at: datetime
    state: ProposalState = "pending"
    rejection_reason: str | None = None

    @field_validator("project_path")
    @classmethod
    def _canonical_project_path(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute() or str(path.resolve()) != value:
            raise ValueError("project_path must be a canonical absolute path")
        return value

    @field_validator("created_at")
    @classmethod
    def _aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class ProposalListReport(BaseModel):
    """Deterministically ordered proposals plus diagnostics for unreadable entries."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    canonical_path: str | None = None
    proposals: list[ProjectProposal] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ProposalActionReport(BaseModel):
    """Result of authorizing or rejecting one proposal; no command execution is implied."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    canonical_path: str | None = None
    project_revision: str | None = None
    proposal: ProjectProposal | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


# --------------------------------------------------------------------------- explain
class DiagnosticHelp(BaseModel):
    """The result of ``arcavex explain``: a documentation entry for a diagnostic code."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    code: str
    found: bool
    title: str | None = None
    summary: str | None = None
    fix: str | None = None
    message: str | None = None  # populated when the code is unknown


# ------------------------------------------------------------------ template authoring
class VariableInfo(BaseModel):
    """A declared template variable, as reported by inspect.

    ``has_default`` distinguishes a variable with no declared default from one declared as
    ``default: null`` (both serialize ``default`` as ``null``), so a machine consumer can
    recover the authored contract exactly (CR-11).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    type: str | None = None
    required: bool = False
    has_default: bool = False
    default: Any = None
    doc: str | None = None
    enum: list[Any] | None = None


class FormatInfo(BaseModel):
    """A declared format's canvas, as reported by inspect.

    ``width``/``height`` echo the authored strings (e.g. ``"1080px"``) so an AI author can
    round-trip a size without converting from the internal points, which ``width_pt`` reports
    for layout math (DX-7).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    width: str | None = None
    height: str | None = None
    width_pt: float
    height_pt: float
    dpi: int


class NodeInfo(BaseModel):
    """An authored node in the template contract, as reported by inspect.

    Nodes are reported as authored, not expanded (DX-3): a ``repeat``/``if`` construct appears
    once with its ``origin`` and the condition/collection expression, so a consumer sees the
    full structural contract regardless of what the preview data happens to instantiate.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    type: str
    origin: Literal["static", "repeat", "if"] = "static"
    condition: str | None = None  # the 'if' expression, for origin == "if"
    collection: str | None = None  # the 'repeat' expression, for origin == "repeat"
    loop_var: str | None = None  # the repeat 'as' name
    key: str | None = None  # the repeat 'key' expression


class FunctionInfo(BaseModel):
    """A registered template function's name, signature, and one-line doc (DX-3)."""

    model_config = ConfigDict(frozen=True)

    name: str
    signature: str
    doc: str | None = None


class LocaleInfo(BaseModel):
    """A declared template locale, as reported by inspect (spec §4.1.1).

    ``direction`` and ``digits`` are the locale's own declared settings (``None`` when the
    locale defaults them); ``has_fonts``/``has_patch`` say whether the locale ships a font
    remap or a structural patch, so an agent learns a template's locale contract — the set of
    locales it supports and what each changes — without deliberately triggering an
    ``ARC-TPL-100`` by guessing a name.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    direction: str | None = None
    digits: str | None = None
    has_fonts: bool = False
    has_patch: bool = False


class TemplateInspectReport(BaseModel):
    """The result of ``arcavex template inspect``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    compiled: bool = False
    version: str | None = None
    is_split: bool = False
    variables: list[VariableInfo] = Field(default_factory=list)
    formats: list[FormatInfo] = Field(default_factory=list)
    locales: list[LocaleInfo] = Field(default_factory=list)
    nodes: list[NodeInfo] = Field(default_factory=list)
    functions: list[FunctionInfo] = Field(default_factory=list)
    preview_data: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ResolvedPatchInfo(BaseModel):
    """One applied patch op and the value it produced, for --resolved output."""

    model_config = ConfigDict(frozen=True)

    layer: str
    op: str
    path: str
    value: Any = None
    effective: bool = True


class TemplateResolvedReport(BaseModel):
    """The result of ``arcavex template inspect --resolved`` (CR-1).

    Reports the resolved format/locale settings and the ordered list of applied format/locale
    patches with the final value each produced and its originating layer. The last op on a
    given path is marked ``effective`` — that is where the final value came from.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    format: str | None = None
    locale: str | None = None
    direction: str | None = None
    digits: str | None = None
    style: str | None = None
    patches: list[ResolvedPatchInfo] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ScaffoldResult(BaseModel):
    """The result of ``arcavex template new``.

    ``format`` is the first declared format (the one the human line says to render with);
    ``formats`` lists every canvas the scaffold declared, in preset order.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    path: str | None = None
    format: str | None = None
    formats: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class CheckResult(BaseModel):
    """The result of ``arcavex template check``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    diagnostics: list[Diagnostic] = Field(default_factory=list)


# ------------------------------------------------------------------ extensions (§3.3, §7)
class ExtensionComponentInfo(BaseModel):
    """One component an extension registers: its kind and globally-unique name."""

    model_config = ConfigDict(frozen=True)

    kind: str
    name: str


class ExtensionSummary(BaseModel):
    """An added extension as reported by ``ext list``: identity, enabled state, components."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    enabled: bool
    components: list[ExtensionComponentInfo] = Field(default_factory=list)


class ExtensionListReport(BaseModel):
    """The result of ``arcavex ext list`` — every added local extension and its state.

    ``load_diagnostics`` carries any problem the loader hit registering enabled extensions at
    engine start (an incompatible or name-colliding extension), so a broken extension surfaces
    here rather than silently doing nothing.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    extensions: list[ExtensionSummary] = Field(default_factory=list)
    load_diagnostics: list[Diagnostic] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ExtensionScaffoldReport(BaseModel):
    """The result of ``arcavex ext scaffold`` — the created extension directory and its files."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    path: str | None = None
    kind: str | None = None
    name: str | None = None
    files: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ExtensionValidateReport(BaseModel):
    """The result of ``arcavex ext validate`` — the manifest/compat/import/determinism checks."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    name: str | None = None
    components: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ExtensionTestReport(BaseModel):
    """The result of ``arcavex ext test`` — the crash-contained golden-fixture run's outcome.

    ``output`` is the captured stdout/stderr of the test subprocess, so a failure's detail (a
    bounds-honesty note, a golden mismatch) travels back to the caller.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    name: str | None = None
    passed: bool = False
    output: str = ""
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ExtensionActionReport(BaseModel):
    """The result of ``arcavex ext add/enable/disable/remove`` — the extension's new state.

    ``removed_path`` is set by ``remove`` to the stored copy it deleted, so the report says what
    left the disk; it stays ``None`` when there was no copy to delete.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    name: str | None = None
    enabled: bool = False
    removed_path: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ExtensionServiceProtocol(Protocol):
    """The extension authoring/lifecycle service injected by bootstrap (spec §7.2).

    Every method returns a versioned kernel result model and does not raise across the facade
    boundary. The concrete implementation lives in ``services.extensions`` and reads/writes the
    added-extension state under the Arcavex home.
    """

    def list_extensions(self, load_diagnostics: list[Diagnostic]) -> ExtensionListReport: ...

    def scaffold_extension(
        self, kind: str, target: Path, name: str | None
    ) -> ExtensionScaffoldReport: ...

    def validate_extension(self, path: Path) -> ExtensionValidateReport: ...

    def test_extension(self, path: Path) -> ExtensionTestReport: ...

    def add_extension(self, path: Path) -> ExtensionActionReport: ...

    def enable_extension(self, name: str) -> ExtensionActionReport: ...

    def disable_extension(self, name: str) -> ExtensionActionReport: ...

    def remove_extension(self, name: str, *, force: bool) -> ExtensionActionReport: ...


class SplitResult(BaseModel):
    """The result of ``arcavex template split``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    directory: str | None = None
    files: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class PatchOp(BaseModel):
    """One path-addressed template mutation (spec §4.1.4), the AI authoring contract.

    Exactly one of ``set``/``remove``/``insert_before``/``insert_after`` names the addressed
    path; ``value`` carries a ``set`` payload and ``node`` the mapping an insert introduces. A
    path is ``nodes.<id>[.<field>...]`` (the only form inserts take) or, because this is the
    top-level operation, a template section: ``formats.<name>``, ``variables.<name>``,
    ``preview_data.<key>``, ``locales.<name>`` (each with an optional field path) or ``style``.
    This is the SAME grammar the format/locale/project override layers use for nodes, applied
    here to the template file itself so an agent edits a stable node id rather than a text span.
    """

    model_config = ConfigDict(frozen=True)

    set: str | None = None
    remove: str | None = None
    insert_before: str | None = None
    insert_after: str | None = None
    value: Any = None
    node: dict[str, Any] | None = None

    def to_patch_dict(self) -> dict[str, Any]:
        """Render this op as the plain ``{verb: path[, value|node]}`` mapping the patcher applies.

        Only the single named verb key is emitted, so the patcher's "exactly one verb" check
        sees one verb (a model with four optional verb fields would otherwise present four).
        A ``set``'s ``value`` is always included — even when it is ``None`` — so setting a field
        to null round-trips; an insert carries its ``node``.
        """
        for verb in ("set", "remove", "insert_before", "insert_after"):
            path = getattr(self, verb)
            if path is None:
                continue
            op: dict[str, Any] = {verb: path}
            if verb == "set":
                op["value"] = self.value
            elif verb in ("insert_before", "insert_after"):
                op["node"] = self.node
            return op
        return {}


class PatchTemplateResult(BaseModel):
    """The result of ``patch_template`` (§3.7, §4.1.4): the mutated file and its new hash.

    ``sha256`` is the content hash of the template file *after* a successful patch (or the
    current on-disk hash when a changed-on-disk check rejects the patch), so an agent can chain
    edits by passing it as the next call's ``base_sha256`` and detect a concurrent edit (§8.3).
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    path: str | None = None
    sha256: str | None = None
    applied: int = 0
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class DataReport(BaseModel):
    """The result of ``set_data``/``import_data`` (§3.7): the written data file and validation.

    ``diagnostics`` are the compile diagnostics of the project's template over the merged data
    (located against the data file), so an agent that sets or imports a value learns whether the
    project still validates without a separate call. Validation here is **compile-only**: it does
    not run the layout pass (that needs render registries the orchestrator does not hold), so a
    data change that overflows a box or overlaps a sibling is not reflected in this report — an
    agent that needs geometric feedback must call ``layout_inspect``/``render_preview`` after a
    data edit (CR-5). A keypath matching no declared variable is surfaced here as an
    ``ARC-TPL-112`` warning so a typo is not a silent no-op (DX-6).
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    path: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class AssetInfo(BaseModel):
    """A CAS-ingested asset as reported to a client: content hash, media type, and metadata.

    Mirrors the service-layer ``AssetRef`` (the kernel cannot import a service model), so the
    facade projects the ingested reference onto this versioned kernel model at the boundary.
    """

    model_config = ConfigDict(frozen=True)

    sha256: str
    mime: str
    width: int
    height: int
    bytes: int
    annotations: dict[str, Any] = Field(default_factory=dict)


class AssetReport(BaseModel):
    """The result of ``add_asset``/``annotate_asset`` (§4.7): the resolved asset and diagnostics."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    asset: AssetInfo | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class PreviewResult(BaseModel):
    """The result of a single ``arcavex preview`` render (watch or one-shot)."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    output_path: str | None = None
    changed_file: str | None = None
    compile_ms: float | None = None
    render_ms: float | None = None
    content_sha256: str | None = None
    inferred: dict[str, str] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class PreviewProjectReport(BaseModel):
    """The result of ``arcavex preview`` in project mode: one preview per format × locale (DX-1)."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    previews: list[PreviewResult] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


# --------------------------------------------------------------------- layout inspection
class AnchorDerivation(BaseModel):
    """How one axis position of a node was derived from its anchor."""

    model_config = ConfigDict(frozen=True)

    axis: Literal["horizontal", "vertical"]
    edge: str  # the pinned edge of this node (physical, after logical resolution)
    expression: str  # e.g. "title.bottom + 16pt"
    resolved_pt: float


class OverflowReport(BaseModel):
    """A node's text-overflow outcome, echoed for inspection.

    ``base_size_pt`` is the authored font size the fit started from and ``resolved_size_pt`` the
    size actually painted, so a ``shrunk`` outcome is judged from the sizes themselves rather
    than from the box extents. ``kind`` is ``shrunk`` only when the size moved by at least the
    larger of 1pt and 2% of the base; a smaller move is a fit-search artefact, left at ``none``
    with the exact resolved size still reported. Both fields are additive under
    response_version 1 and default to ``None`` (spec §2 rule 5).
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    measured_w_pt: float
    measured_h_pt: float
    box_w_pt: float
    box_h_pt: float
    base_size_pt: float | None = None
    resolved_size_pt: float | None = None


class LayoutNodeReport(BaseModel):
    """Resolved geometry and derivation for one node."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    bounds_pt: tuple[float, float, float, float]
    bounds_px: tuple[float, float, float, float]
    paint_bounds_pt: tuple[float, float, float, float]
    paint_bounds_px: tuple[float, float, float, float]
    # The node's absolute affine transform as (a, b, c, d, e, f); identity for unrotated nodes.
    absolute_transform: tuple[float, float, float, float, float, float]
    rotate_deg: float = 0.0
    overflow: OverflowReport | None = None
    anchors: list[AnchorDerivation] = Field(default_factory=list)
    children: list[LayoutNodeReport] = Field(default_factory=list)


OverlapKind = Literal["content", "touch", "halo"]


class SiblingOverlap(BaseModel):
    """Two sibling nodes whose resolved bounds intersect, classified by what collides.

    ``kind``:

    - ``content`` — the nodes' collision boxes intersect: the layout bounds (post-rotation AABB,
      no effect growth), narrowed for an unrotated text node to its shaped width along the
      paragraph alignment. ``rect_pt`` is the colliding area, so its size is the depth to correct.
    - ``touch`` — the collision boxes intersect, but by no more than 1pt on the short side or by
      under 2% of the smaller box's area: a graze or a corner nick, usually intended. ``rect_pt``
      is the same content intersection.
    - ``halo`` — only the effect-grown ``paint_bounds`` intersect: the drop-shadow, glow or
      torn-paper amplitude of one node reaches over its neighbour. ``rect_pt`` is then the
      paint intersection, the only one that exists.

    Containment by structure is not reported at all: a group, a backdrop covering ≥90% of the
    parent region, a stroke-only frame (absent or transparent fill) drawn around the node, or a
    filled plate painted beneath it. A filled shape painted *over* a sibling it fully covers
    hides that sibling and is still ``content``.

    Scope: pairs are enumerated per group, so two nodes in different groups are never compared.
    An empty list means no sibling collisions, not that nothing on the canvas collides — on the
    reference poster, 20-22 intersecting cross-group pairs go unreported per format. Callers
    needing a whole-canvas check compare ``bounds_pt`` across the tree themselves; the reason the
    scope is not simply widened is in docs/backlog.md.
    """

    model_config = ConfigDict(frozen=True)

    a: str
    b: str
    rect_pt: tuple[float, float, float, float]
    # Additive under response_version 1 and defaulted, so a payload serialised before the field
    # existed still parses and a consumer that ignores it is unaffected (spec §2 rule 5).
    kind: OverlapKind = "content"


class LayoutReport(BaseModel):
    """The result of ``arcavex layout inspect`` (versioned JSON)."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    format: str | None = None
    locale: str | None = None
    canvas_pt: tuple[float, float] = (0.0, 0.0)
    canvas_px: tuple[int, int] = (0, 0)
    dpi: int = 0
    root: LayoutNodeReport | None = None
    overlaps: list[SiblingOverlap] = Field(default_factory=list)
    covered_fraction: float = 0.0
    # Maximal full-width empty horizontal bands (uncovered canvas), largest first — the summary
    # that surfaces e.g. an unfilled bottom slab (spec §6.1.1 free regions).
    free_regions: list[tuple[float, float, float, float]] = Field(default_factory=list)
    inferred: dict[str, str] = Field(default_factory=dict)
    warnings: list[Diagnostic] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class LayerSource(BaseModel):
    """Stable authoring location for a layer definition."""

    model_config = ConfigDict(frozen=True)

    file: str | None = None
    keypath: str | None = None
    line: int | None = None


class LayerEffect(BaseModel):
    """One resolved effect declaration attached to a layer."""

    model_config = ConfigDict(frozen=True)

    index: int
    name: str
    category: Literal["geometry", "color", "raster", "composite"] | None = None
    params: dict[str, object] = Field(default_factory=dict)


class LayerMask(BaseModel):
    """One resolved mask declaration attached to a layer."""

    model_config = ConfigDict(frozen=True)

    component: str
    params: dict[str, object] = Field(default_factory=dict)


class LayerNodeReport(BaseModel):
    """One definition, rendered instance, or virtual effect/mask row in a layer tree."""

    model_config = ConfigDict(frozen=True)

    id: str
    authored_id: str
    instance_id: str | None = None
    parent_id: str | None = None
    authored_index: int
    paint_index: int | None = None
    z: int = 0
    kind: str
    origin: Literal["static", "repeat", "if"] = "static"
    condition: str | None = None
    collection: str | None = None
    loop_var: str | None = None
    key: str | None = None
    display_name: str
    #: The authored text of a text node, so an editor can show and diff what it will replace.
    #: Absent for every other kind, and for a rendered instance whose text came from data.
    text: str | None = None
    #: What that text resolved to for this render — bindings filled in, locale applied. Present
    #: in ``rendered`` mode only, and never what an editor writes back: replacing the authored
    #: ``{{ headline }}`` with its resolved value is how a data binding gets destroyed. It is
    #: here so a client can confirm a wording change without rendering a full-size image and
    #: looking at it, which was the only way to check.
    resolved_text: str | None = None
    #: The node's authored ``style`` mapping — font, size, weight, colour, alignment, fill, and
    #: the rest of the vocabulary. Reported so an editor can show a value before changing it;
    #: without it a properties panel can only offer geometry, which is what it did.
    style: dict[str, Any] | None = None
    #: The node's authored ``paragraph`` mapping — ``align`` and ``direction``. Reported apart
    #: from ``style`` because that is where the text renderer reads alignment from: a value
    #: written to ``style.align`` is accepted by the schema and then ignored.
    paragraph: dict[str, Any] | None = None
    visible: bool = True
    locked: bool = False
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    editable: bool = True
    hit_testable: bool = True
    virtual: bool = False
    bounds_pt: _FiniteRect | None = None
    bounds_px: _FiniteRect | None = None
    paint_bounds_pt: _FiniteRect | None = None
    paint_bounds_px: _FiniteRect | None = None
    absolute_transform: _FiniteMatrix | None = None
    rotate_deg: FiniteFloat = 0.0
    overflow: OverflowReport | None = None
    source: LayerSource | None = None
    effects: list[LayerEffect] = Field(default_factory=list)
    mask: LayerMask | None = None
    children: list[LayerNodeReport] = Field(default_factory=list)


class LayerTreeReport(BaseModel):
    """Authoritative desktop layer hierarchy in authored or rendered mode."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    mode: Literal["authored", "rendered"] = "authored"
    format: str | None = None
    locale: str | None = None
    canvas_pt: _FinitePoint = (0.0, 0.0)
    canvas_px: tuple[int, int] = (0, 0)
    dpi: int = 0
    root: LayerNodeReport | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class HitCandidate(BaseModel):
    """One rendered layer whose paint bounds contain the queried canvas point."""

    model_config = ConfigDict(frozen=True)

    id: str
    authored_id: str
    instance_id: str
    parent_id: str | None = None
    kind: Literal["group", "text", "image", "shape", "path"]
    display_name: str
    editable: bool
    locked: bool
    bounds_pt: _FiniteRect
    paint_bounds_pt: _FiniteRect


class HitTestReport(BaseModel):
    """Topmost-first geometry hit-test result in canonical canvas point space."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    format: str | None = None
    locale: str | None = None
    point_pt: _FinitePoint = (0.0, 0.0)
    point_px: _FinitePoint | None = None
    candidates: list[HitCandidate] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class AuthoringProtocol(Protocol):
    """Template authoring operations injected by bootstrap (scaffold/inspect/split)."""

    def scaffold(
        self, name: str, target: Path, formats: list[str] | None = None
    ) -> ScaffoldResult:
        """Scaffold a new renderable template directory at ``target`` declaring ``formats``."""
        ...

    def inspect(self, template: Path) -> TemplateInspectReport:
        """Inspect a template's variables, formats, nodes, and functions."""
        ...

    def split(self, template: Path) -> SplitResult:
        """Convert a one-file template into a split directory losslessly."""
        ...

    def patch_template(
        self, template: Path, ops: list[PatchOp], base_sha256: str | None
    ) -> PatchTemplateResult:
        """Apply path-addressed patch ops to a template file on disk (ruamel round-trip)."""
        ...


# ------------------------------------------------------ projects, library, provenance (§5)
class ProjectResult(BaseModel):
    """The result of ``arcavex project new`` — the scaffolded project's shape."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    path: str | None = None
    name: str | None = None
    template: str | None = None
    style: str | None = None
    formats: list[str] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=list)
    status: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ProjectStatusReport(BaseModel):
    """The result of ``arcavex status`` — the resolved project and its recorded-run count."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    name: str | None = None
    template: str | None = None
    style: str | None = None
    status: str | None = None
    formats: list[str] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    data: str | None = None
    root: str | None = None
    runs: int = 0
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class LibraryTemplateInfo(BaseModel):
    """One published library template: its name, available versions, and default alias."""

    model_config = ConfigDict(frozen=True)

    name: str
    versions: list[str] = Field(default_factory=list)
    default: str | None = None


class TemplateListReport(BaseModel):
    """The result of ``list_templates`` — every published library template (§5.1)."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    templates: list[LibraryTemplateInfo] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    """One discovered project's identity for ``list_projects`` output."""

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    status: str | None = None
    template: str | None = None


class ProjectListReport(BaseModel):
    """The result of ``list_projects`` — projects discovered under a root directory."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    projects: list[ProjectSummary] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class RunReport(BaseModel):
    """The result of a recorded render (project or ``--record``): the run dir and its outputs."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    run_id: str | None = None
    run_dir: str | None = None
    outputs: list[str] = Field(default_factory=list)
    inferred: dict[str, str] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class RunInfo(BaseModel):
    """One run's summary row for ``arcavex list-runs``."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    created: str
    kind: str
    project: str | None = None
    engine_version: str = ""
    platform: str = ""
    outputs: list[str] = Field(default_factory=list)


class RunListReport(BaseModel):
    """The result of ``arcavex list-runs``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    runs: list[RunInfo] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class RerunReport(BaseModel):
    """The result of ``arcavex rerun``: a new run plus whether it reproduced the original bytes."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    source_run: str | None = None
    run_id: str | None = None
    run_dir: str | None = None
    reproduced: bool = False
    engine_match: bool = True
    platform_match: bool = True
    mismatches: list[str] = Field(default_factory=list)
    # Which recorded inputs changed on disk since the run was recorded (template, overrides,
    # style, assets, fonts). Explains a failed reproduction whose engine and platform both
    # match — the byte comparison flags drift, this names its cause (CR-3/DX-3).
    drift: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class OutputDiff(BaseModel):
    """The per-output comparison between two runs: presence, byte-identity, and DSSIM."""

    model_config = ConfigDict(frozen=True)

    name: str
    in_a: bool
    in_b: bool
    identical: bool = False
    dssim: float | None = None


class MetadataDiff(BaseModel):
    """One differing provenance field between two runs (template, data, engine, …)."""

    model_config = ConfigDict(frozen=True)

    field: str
    a: str | None
    b: str | None


class DiffReport(BaseModel):
    """The result of ``arcavex diff`` (spec §5.3): per-output pixels plus metadata changes."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    run_a: str | None = None
    run_b: str | None = None
    outputs: list[OutputDiff] = Field(default_factory=list)
    metadata: list[MetadataDiff] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class BatchEntry(BaseModel):
    """One project's outcome within a batch render."""

    model_config = ConfigDict(frozen=True)

    project: str
    ok: bool
    run_id: str | None = None
    run_dir: str | None = None
    outputs: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class BatchReport(BaseModel):
    """The result of ``arcavex batch``: one entry per project, rendered in parallel jobs."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    jobs: int = 1
    entries: list[BatchEntry] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class PublishReport(BaseModel):
    """The result of ``arcavex template publish``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    name: str | None = None
    version: str | None = None
    path: str | None = None
    default: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class DetachReport(BaseModel):
    """The result of ``arcavex template detach`` (copies a library template into a project)."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    template: str | None = None
    path: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class UpgradeOutputDiff(BaseModel):
    """One output's perceptual difference between the current pin and the upgrade target.

    ``patch_applied`` is false when the project override no longer resolves against the target
    version, so the target-version preview was rendered *without* the override (the diff still
    shows what the new version looks like over current data, §5.5).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    dssim: float | None = None
    patch_applied: bool = True


class UpgradeStalePath(BaseModel):
    """One project override op that no longer resolves against the upgrade target (DX-5).

    Reports the addressed node path and id (not just the op index) plus the located diagnostic
    detail, the same information the render-time ``ARC-TPL-092`` gives.
    """

    model_config = ConfigDict(frozen=True)

    op: str  # the patch-list position, e.g. "project.patch[0]"
    path: str | None = None  # the addressed path, e.g. "nodes.venue.style.font_size"
    node_id: str | None = None  # the addressed node id, e.g. "venue"
    detail: str | None = None  # the ARC-TPL-092 message


class UpgradeReport(BaseModel):
    """The result of ``arcavex project upgrade``: a preview; updates the pin only when applied.

    Implements the spec §5.5 five steps: compile old + target over current data, report stale
    override paths (``stale`` / ``stale_paths``) with a structural node diff (``added_nodes`` /
    ``removed_nodes``), render comparable previews and their perceptual diff (``outputs``), and
    update the pin only on ``applied``.
    """

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    from_version: str | None = None
    to_version: str | None = None
    stale_paths: list[str] = Field(default_factory=list)
    stale: list[UpgradeStalePath] = Field(default_factory=list)
    added_nodes: list[str] = Field(default_factory=list)
    removed_nodes: list[str] = Field(default_factory=list)
    outputs: list[UpgradeOutputDiff] = Field(default_factory=list)
    applied: bool = False
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class OrchestratorProtocol(Protocol):
    """Project/library/provenance operations injected by bootstrap (spec §5).

    The concrete implementation lives in the service layer and drives the pipeline through an
    injected renderer, so the kernel facade delegates without importing services or built-ins.
    Every method returns a versioned kernel result model and does not raise across the boundary.
    """

    def create_project(
        self,
        target: Path,
        name: str,
        template_ref: str,
        style: str | None,
        formats: list[str] | None,
        locales: list[str] | None,
    ) -> ProjectResult: ...

    def project_status(self, start: Path | None, project: Path | None) -> ProjectStatusReport: ...

    def project_snapshot(
        self,
        start: Path | None,
        project: Path | None,
        capabilities: list[str],
    ) -> ProjectSnapshotReport: ...

    def layer_tree(
        self,
        start: Path | None,
        project: Path | None,
        mode: Literal["authored", "rendered"],
        format_name: str | None,
        locale: str | None,
    ) -> LayerTreeReport: ...

    def hit_test(
        self,
        start: Path | None,
        project: Path | None,
        point_pt: tuple[float, float],
        format_name: str | None,
        locale: str | None,
    ) -> HitTestReport: ...

    def project_ui_metadata(
        self, start: Path | None, project: Path | None
    ) -> ProjectUIMetadataReport: ...

    def set_project_ui_metadata(
        self,
        start: Path | None,
        project: Path | None,
        metadata: ProjectUIMetadata,
    ) -> ProjectUIMetadataReport: ...

    def project_policy(
        self, start: Path | None, project: Path | None
    ) -> ProjectPolicyReport: ...

    def set_project_policy(
        self,
        start: Path | None,
        project: Path | None,
        mode: AutomationMode,
        extensions: ExtensionMode,
    ) -> ProjectPolicyReport: ...

    def list_project_proposals(
        self, start: Path | None, project: Path | None
    ) -> ProposalListReport: ...

    def approve_project_proposal(
        self, start: Path | None, project: Path | None, command_id: str
    ) -> ProposalActionReport: ...

    def reject_project_proposal(
        self,
        start: Path | None,
        project: Path | None,
        command_id: str,
        reason: str,
    ) -> ProposalActionReport: ...

    def clone_project(
        self, start: Path | None, project: Path | None, target: Path, name: str
    ) -> ProjectResult: ...

    def set_project_status(
        self, start: Path | None, project: Path | None, status: str
    ) -> ProjectStatusReport: ...

    def render_project(
        self,
        start: Path | None,
        project: Path | None,
        formats: list[str] | None,
        locales: list[str] | None,
        dpi: int | None,
    ) -> RunReport: ...

    def record_render(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        dpi: int | None,
        outputs_root: Path | None,
    ) -> RunReport: ...

    def list_runs(
        self, start: Path | None, project: Path | None, path: Path | None
    ) -> RunListReport: ...

    def project_inputs(
        self,
        start: Path | None,
        project: Path | None,
        formats: list[str] | None,
        locales: list[str] | None,
    ) -> ProjectInputs: ...

    def rerun(self, run_dir: Path) -> RerunReport: ...

    def diff(self, run_a: Path, run_b: Path) -> DiffReport: ...

    def batch_render(
        self, globs: list[str], jobs: int, dpi: int | None
    ) -> BatchReport: ...

    def upgrade_project(
        self, start: Path | None, project: Path | None, to_version: str, apply: bool
    ) -> UpgradeReport: ...

    def publish_template(
        self, template: Path, name: str, version: str, set_default: bool
    ) -> PublishReport: ...

    def detach_template(self, start: Path | None, project: Path | None) -> DetachReport: ...

    def set_data(
        self, start: Path | None, project: Path | None, keypath: str, value: Any
    ) -> DataReport: ...

    def import_data(
        self, start: Path | None, project: Path | None, yaml_text: str, locale: str | None
    ) -> DataReport: ...

    def add_asset(
        self, start: Path | None, project: Path | None, source: Path
    ) -> AssetReport: ...

    def annotate_asset(
        self, sha256: str, annotations: dict[str, Any]
    ) -> AssetReport: ...

    def list_templates(self) -> TemplateListReport: ...

    def list_projects(self, root: Path | None) -> ProjectListReport: ...


class BudgetProtocol(Protocol):
    """Per-render resource budget injected by bootstrap (kept out of the pure kernel, §8.3).

    Both checks raise a ``DiagnosticError`` (an ``ARC-RND`` budget code) when a limit is exceeded,
    so an oversized render is refused with a located diagnostic and exit 4.
    """

    def check_surface(self, width_px: int, height_px: int, *, file: str | None = ...) -> None: ...

    def check_wall_ms(self, elapsed_ms: float, *, file: str | None = ...) -> None: ...


class Facade:
    """Orchestrates the pipeline using injected, kernel-external dependencies."""

    def __init__(
        self,
        registries: Registries,
        compiler: CompilerProtocol,
        measure_fn: MeasureFn,
        *,
        default_layout: str = "anchors",
        default_backend: str = "skia",
        doctor_probe: Callable[[], DoctorReport] | None = None,
        explain_lookup: Callable[[str], DiagnosticHelp] | None = None,
        authoring: AuthoringProtocol | None = None,
        preview_root: Path | None = None,
        style_provider: StyleProviderProtocol | None = None,
        orchestrator: OrchestratorProtocol | None = None,
        extensions: ExtensionServiceProtocol | None = None,
        extension_load_diagnostics: list[Diagnostic] | None = None,
        fonts: FontServiceProtocol | None = None,
        skills: SkillServiceProtocol | None = None,
        mcp_hosts: McpHostServiceProtocol | None = None,
        budget: BudgetProtocol | None = None,
        engine_version: str = "",
        desktop: DesktopServiceProtocol | None = None,
        editor: EditorProtocol | None = None,
    ) -> None:
        """Wire the facade.

        Args:
            registries: The populated component registries.
            compiler: The template compiler.
            measure_fn: The text measurement function used by layout.
            default_layout: Name of the default layout solver.
            default_backend: Name of the default renderer backend.
            doctor_probe: Callable returning the environment doctor report.
            explain_lookup: Callable resolving a diagnostic code to help.
            authoring: The template authoring service (scaffold/inspect/split).
            preview_root: Directory for stable preview outputs (defaults to an OS temp dir).
        """
        self._registries = registries
        self._compiler = compiler
        self._measure = measure_fn
        self._default_layout = default_layout
        self._default_backend = default_backend
        self._doctor_probe = doctor_probe
        self._explain_lookup = explain_lookup
        self._authoring = authoring
        self._preview_root = preview_root
        self._style_provider = style_provider
        self._orchestrator = orchestrator
        self._extensions = extensions
        self._extension_load_diagnostics = list(extension_load_diagnostics or [])
        self._fonts = fonts
        self._skills = skills
        self._mcp_hosts = mcp_hosts
        self._budget = budget
        self._engine_version = engine_version
        self._desktop = desktop
        self._editor = editor

    # ------------------------------------------------------------------ semantic editor
    def editor_apply(self, transaction: dict[str, Any]) -> TransactionReport:
        """Execute one semantic transaction against its project. Never raises."""
        if self._editor is None:  # pragma: no cover - always wired in production
            return TransactionReport(ok=False, diagnostics=[_unwired("editor")])
        try:
            return self._editor.apply(transaction)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return TransactionReport(
                ok=False, diagnostics=[internal_error("Editor apply failed", detail=repr(exc))]
            )

    def editor_apply_authorized(self, project: Path, command_id: str) -> TransactionReport:
        """Execute a proposal a person authorized, re-checked against the fresh revision."""
        if self._editor is None:  # pragma: no cover - always wired in production
            return TransactionReport(ok=False, diagnostics=[_unwired("editor")])
        try:
            return self._editor.apply_authorized(project, command_id)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return TransactionReport(
                ok=False,
                diagnostics=[internal_error("Editor authorized apply failed", detail=repr(exc))],
            )

    def editor_undo(self, project: Path) -> TransactionReport:
        """Restore the state before the newest applied history entry. Never raises."""
        if self._editor is None:  # pragma: no cover - always wired in production
            return TransactionReport(ok=False, diagnostics=[_unwired("editor")])
        try:
            return self._editor.undo(project)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return TransactionReport(
                ok=False, diagnostics=[internal_error("Editor undo failed", detail=repr(exc))]
            )

    def editor_redo(self, project: Path) -> TransactionReport:
        """Re-apply the oldest undone history entry. Never raises."""
        if self._editor is None:  # pragma: no cover - always wired in production
            return TransactionReport(ok=False, diagnostics=[_unwired("editor")])
        try:
            return self._editor.redo(project)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return TransactionReport(
                ok=False, diagnostics=[internal_error("Editor redo failed", detail=repr(exc))]
            )

    def editor_history(self, project: Path) -> HistoryReport:
        """The project's undo/redo state. Never raises."""
        if self._editor is None:  # pragma: no cover - always wired in production
            return HistoryReport(ok=False, diagnostics=[_unwired("editor")])
        try:
            return self._editor.history(project)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return HistoryReport(
                ok=False, diagnostics=[internal_error("Editor history failed", detail=repr(exc))]
            )

    def validate_template(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> list[Diagnostic]:
        """Compile through semantic validation and return accumulated diagnostics.

        Never raises: unexpected failures are returned as an ``ARC-INT-999`` diagnostic.
        """
        try:
            targets: list[str | None]
            if format_name is None:
                formats = self._compiler.list_formats(template)
                # Validate against every declared format when the choice is ambiguous, so
                # a caller need not pick one just to check the template structurally.
                targets = list(formats) if len(formats) > 1 else [None]
            else:
                targets = [format_name]

            aggregated: list[Diagnostic] = []
            for target in targets:
                aggregated.extend(
                    self._validate_one(template, data, target, locale, style)
                )
            return _dedupe(aggregated)
        except DiagnosticError as exc:
            return list(exc.diagnostics)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return [internal_error("Validation failed unexpectedly", detail=repr(exc))]

    def _validate_one(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
    ) -> list[Diagnostic]:
        result = self._compiler.compile(template, data, format_name, locale, style)
        diagnostics = list(result.diagnostics)
        if result.document is not None and not has_errors(diagnostics):
            # Exercise layout so under/over-constrained nodes surface during validate.
            diagnostics.extend(self._try_layout(result.document))
        return diagnostics

    def render_file(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
        output: Path | None = None,
        dpi: int | None = None,
        debug: bool = False,
        quality: int | None = None,
        lossless: bool = False,
    ) -> RenderResult:
        """Compile, lay out, render, and export a template to ``output``.

        The exporter is chosen from ``output``'s extension (``.png``/``.jpg``/``.jpeg``/``.webp``/
        ``.pdf``); ``quality`` sets the lossy encoder quality and ``lossless`` selects lossless
        WebP. Never raises: unexpected failures are returned in the result's diagnostics.

        The default output name (§6.3) is resolved up front from the template stem and the
        resolved format and carried in ``inferred`` on *every* return path — success, a
        ``DiagnosticError``, or an unexpected failure — so the user always learns what would
        have been written, even when the render fails (CR-1).
        """
        inferred_base: dict[str, str] = {}
        resolved_output = output
        if output is None:
            default_output = self._default_output_path(template, format_name, locale)
            if default_output is not None:
                resolved_output = default_output
                inferred_base["output"] = str(default_output)
        try:
            return self._render_file_inner(
                template, data, format_name, locale, style, resolved_output, dpi, debug,
                inferred_base, quality, lossless,
            )
        except DiagnosticError as exc:
            return RenderResult(
                ok=False,
                output_path=None,
                diagnostics=list(exc.diagnostics),
                inferred=dict(inferred_base),
            )
        except Exception:  # noqa: BLE001 - facade boundary must not leak
            last_line = traceback.format_exc().splitlines()[-1]
            return RenderResult(
                ok=False,
                output_path=None,
                diagnostics=[internal_error("Render failed unexpectedly", detail=last_line)],
                inferred=dict(inferred_base),
            )

    def render_plan(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        output: Path | None = None,
        locale: str | None = None,
    ) -> dict[str, str]:
        """Resolve the render-affecting inferences (output name, sole format) up front (RR1-3).

        These are cheap to compute without compiling, so a client can announce them before a
        long render begins rather than only after it finishes. Never raises.
        """
        inferred: dict[str, str] = {}
        try:
            if output is None:
                default = self._default_output_path(template, format_name, locale)
                if default is not None:
                    inferred["output"] = str(default)
            if format_name is None:
                formats = self._compiler.list_formats(template)
                if len(formats) == 1:
                    inferred["format"] = formats[0]
        except Exception:  # noqa: BLE001 - a best-effort plan must never fail the render
            return inferred
        return inferred

    # ------------------------------------------------------------------ internals
    def _default_stem(self, template: Path) -> str:
        """Return the default output stem for a template path (directory name or file stem).

        A directory template, or its ``template.yaml`` file, both yield the directory name, so
        the two spellings produce identical default names (CR-4). A one-file template named
        something other than ``template.yaml`` yields that file's stem.
        """
        try:
            root_dir, template_yaml = self._compiler.resolve_paths(template)
        except Exception:  # noqa: BLE001 - fall back to the raw path when resolution fails
            return Path(template).stem
        if template_yaml.name == "template.yaml":
            # Resolve first: passing "template.yaml" from inside its own directory makes
            # root_dir "." whose .name is empty, which would yield a hidden ".square.png"
            # output. The absolute directory name is the intended stem (RR2-4).
            return root_dir.resolve().name or "output"
        return template_yaml.stem

    def _default_output_path(
        self, template: Path, format_name: str | None, locale: str | None = None
    ) -> Path | None:
        """Resolve the deterministic default output path, or ``None`` if the format is ambiguous.

        The name follows §6.3: ``<stem>.<format>[.<locale>].png``. The format follows the same
        sole-format inference the compiler uses, so the name is available before rendering; when
        several formats exist and none was chosen the name is genuinely unknown (ambiguity is a
        diagnostic, not a silent pick). The locale segment is present only when a locale is
        applied, so ``--locale fa`` never overwrites the ``en`` render (DX-3).
        """
        fmt = format_name
        if fmt is None:
            formats = self._compiler.list_formats(template)
            if len(formats) != 1:
                return None
            fmt = formats[0]
        return Path(_output_name(self._default_stem(template), fmt, locale))

    def _render_file_inner(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        output: Path | None,
        dpi: int | None,
        debug: bool,
        inferred_base: dict[str, str],
        quality: int | None = None,
        lossless: bool = False,
    ) -> RenderResult:
        compiled = self._compiler.compile(template, data, format_name, locale, style)
        diagnostics = list(compiled.diagnostics)
        inferred = {**inferred_base, **dict(compiled.inferred)}
        if compiled.document is None or has_errors(diagnostics):
            return RenderResult(
                ok=False, output_path=None, diagnostics=diagnostics, inferred=inferred
            )

        if output is None:
            # Safety net for the ambiguous-format path (compile normally raises ARC-TPL-021
            # before here): name from the format the compiler actually resolved.
            fmt = compiled.format_name or "out"
            output = Path(_output_name(self._default_stem(template), fmt, locale))
            inferred["output"] = str(output)

        exporter_name = _EXPORTER_BY_EXT.get(output.suffix.lower())
        if exporter_name is None:
            supported = ", ".join(sorted(_EXPORTER_BY_EXT))
            return RenderResult(
                ok=False,
                output_path=None,
                inferred=inferred,
                diagnostics=[
                    diagnostic(
                        "ARC-EXP-011",
                        f"Unsupported output extension {output.suffix!r}",
                        hint=f"Use one of the supported output extensions: {supported}.",
                    )
                ],
            )

        canvas = compiled.document.canvas
        surface, _, warnings = self._layout_and_render(
            compiled.document, dpi, debug=debug, file=str(template)
        )
        diagnostics.extend(warnings)

        exporter = self._registries.exporters.get(exporter_name)
        opts = ExportOptions(
            quality=quality if quality is not None else _DEFAULT_EXPORT_QUALITY,
            dpi=dpi,
            lossless=lossless,
            page_width_pt=canvas.width_pt,
            page_height_pt=canvas.height_pt,
            bleed_pt=canvas.bleed_pt,
            engine_version=self._engine_version,
        )
        # Filesystem failures when publishing the output (an unwritable directory, a parent
        # path component that is a file, a full disk) are the user's problem, not an engine
        # bug: turn the raw OSError into a located ARC-EXP-001 so it reports as an actionable
        # export failure (exit 1) instead of leaking as ARC-INT-999/exit 5 (DX-2). The encoder
        # itself raises its own ARC-EXP-002/003 before any bytes are written.
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            report = exporter.export(surface, output, opts)
        except OSError as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-EXP-001",
                    f"Could not write the output file {str(output)!r}: {exc.strerror or exc}",
                    file=str(output),
                    hint="Check the output path is writable and its parent directory exists.",
                )
            ) from exc

        return RenderResult(
            ok=True,
            # Absolute, so the path means the same thing to a reader in any working directory.
            output_path=str(Path(report.path).resolve()),
            diagnostics=diagnostics,
            content_sha256=report.content_sha256,
            inferred=inferred,
        )

    def _layout_and_render(
        self,
        document: CompiledDocument,
        dpi: int | None,
        *,
        debug: bool = False,
        file: str | None = None,
    ) -> tuple[Any, LayoutDocument, list[Diagnostic]]:
        """Solve and render ``document`` with this facade's registered components."""
        return layout_and_render(
            solver=self._registries.layouts.get(self._default_layout),
            backend=self._registries.backends.get(self._default_backend),
            measure=self._measure,
            document=document,
            dpi=dpi,
            debug=debug,
            budget=self._budget,
            file=file,
        )

    def _export_replace(self, surface: Any, out_path: Path, dpi: int | None) -> Any:
        """Export ``surface`` to ``out_path`` via a same-directory temp file and ``os.replace``.

        A watcher never observes a torn PNG, and a failed render leaves the previous file intact.
        """
        exporter = self._registries.exporters.get("png")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(out_path.parent), prefix=".preview-", suffix=".png"
        )
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)
        try:
            report = exporter.export(surface, tmp_path, ExportOptions(dpi=dpi))
            os.replace(tmp_path, out_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        return report

    def _try_layout(self, document: CompiledDocument) -> list[Diagnostic]:
        try:
            solver = self._registries.layouts.get(self._default_layout)
            layout = solver.solve(document, self._measure)
            # Layout raises warnings (missing glyphs, fit non-convergence) that validate
            # should surface alongside compile diagnostics.
            return list(layout.warnings)
        except DiagnosticError as exc:
            return list(exc.diagnostics)

    # ------------------------------------------------------------------ layout inspect
    def inspect_layout(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> LayoutReport:
        """Compile and lay out a template and report resolved geometry. Never raises.

        Reports per-node resolved bounds (points and device pixels), paint bounds, rotation,
        text-overflow state, the anchor derivation for each axis, sibling overlaps, and a
        coverage summary (spec §6.1.1).
        """
        try:
            return self._inspect_layout_inner(template, data, format_name, locale, style)
        except DiagnosticError as exc:
            return LayoutReport(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return LayoutReport(
                ok=False, diagnostics=[internal_error("Layout inspect failed", detail=repr(exc))]
            )

    def _inspect_layout_inner(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
    ) -> LayoutReport:
        compiled = self._compiler.compile(template, data, format_name, locale, style)
        diagnostics = list(compiled.diagnostics)
        inferred = dict(compiled.inferred)
        if compiled.document is None or has_errors(diagnostics):
            return LayoutReport(
                ok=False, format=format_name, locale=locale, inferred=inferred,
                diagnostics=diagnostics,
            )
        solver = self._registries.layouts.get(self._default_layout)
        layout = solver.solve(compiled.document, self._measure)
        dpi = compiled.document.canvas.dpi
        overlaps: list[SiblingOverlap] = []
        root = _build_node_report(
            compiled.document.root, layout.root, compiled.document.root.direction, dpi, overlaps
        )
        covered = _covered_fraction(layout)
        return LayoutReport(
            ok=True,
            format=compiled.format_name or format_name,
            locale=locale,
            canvas_pt=(compiled.document.canvas.width_pt, compiled.document.canvas.height_pt),
            canvas_px=(compiled.document.canvas.width_px, compiled.document.canvas.height_px),
            dpi=dpi,
            root=root,
            overlaps=overlaps,
            covered_fraction=covered,
            free_regions=_free_regions(layout),
            inferred=inferred,
            warnings=list(layout.warnings),
            diagnostics=diagnostics,
        )

    # ------------------------------------------------------------------ authoring
    def engine_handshake(self) -> EngineHandshakeReport:
        """Return the desktop startup contract from the injected identity service."""
        if self._desktop is None:
            return self._desktop_failure_report(
                "Desktop service is not wired",
                "Build the facade through arcavex.bootstrap.build_facade().",
            )
        try:
            return self._desktop.handshake()
        except Exception as exc:  # noqa: BLE001 - facade boundary must never leak exceptions
            return self._desktop_failure_report(
                "Desktop handshake failed unexpectedly",
                f"Please report this with your environment details. Detail: {exc!r}",
            )

    def _desktop_failure_report(self, message: str, hint: str) -> EngineHandshakeReport:
        """Build the stable fallback shape for missing or failed desktop service wiring."""
        doctor = self.doctor()
        return EngineHandshakeReport(
            ok=False,
            identity=EngineIdentity(engine_version=doctor.engine_version),
            mcp_contract_version="",
            accepted_ir_versions=[],
            produced_ir_version="",
            extension_sdk_version="",
            capabilities=[],
            paths=EnginePaths(
                home="",
                assets="",
                cache="",
                extensions="",
                fonts="",
                styles="",
                templates="",
            ),
            doctor=doctor,
            diagnostics=[diagnostic("ARC-INT-999", message, hint=hint)],
        )

    def doctor(self) -> DoctorReport:
        """Run environment probes and return a report. Never raises."""
        if self._doctor_probe is None:  # pragma: no cover - always wired in production
            return DoctorReport(
                ok=False,
                engine_version="unknown",
                checks=[
                    DoctorCheck(
                        name="doctor",
                        status="fail",
                        detail="doctor probe is not wired",
                        hint="This is a build configuration error.",
                    )
                ],
            )
        try:
            return self._doctor_probe()
        except Exception as exc:  # noqa: BLE001 - doctor must never crash
            return DoctorReport(
                ok=False,
                engine_version="unknown",
                checks=[
                    DoctorCheck(
                        name="doctor",
                        status="fail",
                        detail=f"doctor failed unexpectedly: {exc!r}",
                        hint="Please report this with your environment details.",
                    )
                ],
            )

    def explain_diagnostic(self, code: str) -> DiagnosticHelp:
        """Return documentation for a diagnostic code. Never raises."""
        normalized = code.strip().upper()
        if self._explain_lookup is None:  # pragma: no cover - always wired in production
            return DiagnosticHelp(
                code=normalized, found=False, message="explain is not wired"
            )
        try:
            return self._explain_lookup(normalized)
        except Exception as exc:  # noqa: BLE001 - explain must never crash
            return DiagnosticHelp(
                code=normalized, found=False, message=f"explain failed: {exc!r}"
            )

    def list_styles(self) -> StyleListReport:
        """List every discoverable style pack (spec §3.7). Never raises."""
        if self._style_provider is None:  # pragma: no cover - always wired in production
            return StyleListReport(ok=False, diagnostics=[_unwired("styles")])
        try:
            packs = [_style_summary(p) for p in self._style_provider.list_packs()]
            return StyleListReport(ok=True, styles=packs)
        except DiagnosticError as exc:
            return StyleListReport(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return StyleListReport(
                ok=False, diagnostics=[internal_error("style list failed", detail=repr(exc))]
            )

    def inspect_style(self, ref: str) -> StyleInspectReport:
        """Load and report one style pack by ``name@version`` reference. Never raises."""
        if self._style_provider is None:  # pragma: no cover - always wired in production
            return StyleInspectReport(ok=False, diagnostics=[_unwired("styles")])
        try:
            return StyleInspectReport(
                ok=True, style=_style_summary(self._style_provider.inspect(ref))
            )
        except DiagnosticError as exc:
            return StyleInspectReport(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return StyleInspectReport(
                ok=False, diagnostics=[internal_error("style inspect failed", detail=repr(exc))]
            )

    def list_effects(self) -> EffectListReport:
        """List every registered effect with its category and parameter schema (DX-6).

        A discovery surface parallel to :meth:`list_styles`: an AI or human author can read
        each effect's real param names, types, defaults, and ranges without triggering an
        error or reading source. Never raises.
        """
        try:
            infos: list[EffectInfo] = []
            for name in self._registries.effects.names():
                effect = self._registries.effects.get(name)
                infos.append(
                    EffectInfo(
                        name=name,
                        category=effect.kind.value,
                        params=param_infos(effect.param_schema),
                    )
                )
            return EffectListReport(ok=True, effects=infos)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return EffectListReport(
                ok=False, diagnostics=[internal_error("effects list failed", detail=repr(exc))]
            )

    def list_shapes(self) -> ShapeListReport:
        """List every registered shape generator with its parameter schema. Never raises.

        The generator counterpart of :meth:`list_effects`: nothing over the CLI or MCP listed
        the ``generator:`` names a shape node may use, so an author learned ``starburst``'s
        parameters from an ``ARC-FX-912`` refusal or from source. Each entry carries the
        generator's one-line description and its params' names, types, defaults, and ranges.
        """
        try:
            shapes: list[ShapeInfo] = []
            for name in self._registries.shapes.names():
                generator = self._registries.shapes.get(name)
                shapes.append(
                    ShapeInfo(
                        name=name,
                        description=_first_doc_line(generator.__doc__),
                        params=param_infos(generator.param_schema),
                    )
                )
            return ShapeListReport(ok=True, shapes=shapes)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ShapeListReport(
                ok=False, diagnostics=[internal_error("shapes list failed", detail=repr(exc))]
            )

    # ------------------------------------------------------------------ extensions (§7)
    def list_extensions(self) -> ExtensionListReport:
        """List every added local extension and its enabled state (spec §7.2). Never raises.

        Carries any extension-load diagnostics from engine construction (an incompatible or
        name-colliding enabled extension), so a broken extension is visible here.
        """
        if self._extensions is None:  # pragma: no cover - always wired in production
            return ExtensionListReport(ok=False, diagnostics=[_unwired("extensions")])
        try:
            return self._extensions.list_extensions(self._extension_load_diagnostics)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ExtensionListReport(
                ok=False, diagnostics=[internal_error("ext list failed", detail=repr(exc))]
            )

    def scaffold_extension(
        self, kind: str, target: Path, name: str | None = None
    ) -> ExtensionScaffoldReport:
        """Scaffold a new, immediately-valid extension directory of ``kind``. Never raises."""
        if self._extensions is None:  # pragma: no cover - always wired in production
            return ExtensionScaffoldReport(ok=False, diagnostics=[_unwired("extensions")])
        try:
            return self._extensions.scaffold_extension(kind, Path(target), name)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ExtensionScaffoldReport(
                ok=False, diagnostics=[internal_error("ext scaffold failed", detail=repr(exc))]
            )

    def validate_extension(self, path: Path) -> ExtensionValidateReport:
        """Run the extension validation gates (manifest, compat, imports, determinism). No raise."""
        if self._extensions is None:  # pragma: no cover - always wired in production
            return ExtensionValidateReport(ok=False, diagnostics=[_unwired("extensions")])
        try:
            return self._extensions.validate_extension(Path(path))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ExtensionValidateReport(
                ok=False, diagnostics=[internal_error("ext validate failed", detail=repr(exc))]
            )

    def test_extension(self, path: Path) -> ExtensionTestReport:
        """Run an extension's golden fixtures in a crash-contained subprocess. Never raises."""
        if self._extensions is None:  # pragma: no cover - always wired in production
            return ExtensionTestReport(ok=False, diagnostics=[_unwired("extensions")])
        try:
            return self._extensions.test_extension(Path(path))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ExtensionTestReport(
                ok=False, diagnostics=[internal_error("ext test failed", detail=repr(exc))]
            )

    def add_extension(self, path: Path) -> ExtensionActionReport:
        """Validate and add a local extension to the state, recorded disabled. Never raises."""
        if self._extensions is None:  # pragma: no cover - always wired in production
            return ExtensionActionReport(ok=False, diagnostics=[_unwired("extensions")])
        try:
            return self._extensions.add_extension(Path(path))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ExtensionActionReport(
                ok=False, diagnostics=[internal_error("ext add failed", detail=repr(exc))]
            )

    def enable_extension(self, name: str) -> ExtensionActionReport:
        """Enable an added extension (registered on the next engine start). Never raises."""
        if self._extensions is None:  # pragma: no cover - always wired in production
            return ExtensionActionReport(ok=False, diagnostics=[_unwired("extensions")])
        try:
            return self._extensions.enable_extension(name)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ExtensionActionReport(
                ok=False, diagnostics=[internal_error("ext enable failed", detail=repr(exc))]
            )

    def disable_extension(self, name: str) -> ExtensionActionReport:
        """Disable an added extension (deregistered on the next engine start). Never raises."""
        if self._extensions is None:  # pragma: no cover - always wired in production
            return ExtensionActionReport(ok=False, diagnostics=[_unwired("extensions")])
        try:
            return self._extensions.disable_extension(name)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ExtensionActionReport(
                ok=False, diagnostics=[internal_error("ext disable failed", detail=repr(exc))]
            )

    def remove_extension(self, name: str, *, force: bool = False) -> ExtensionActionReport:
        """Remove an added extension's stored copy and record; enabled needs ``force``. No raise."""
        if self._extensions is None:  # pragma: no cover - always wired in production
            return ExtensionActionReport(ok=False, diagnostics=[_unwired("extensions")])
        try:
            return self._extensions.remove_extension(name, force=force)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ExtensionActionReport(
                ok=False, diagnostics=[internal_error("ext remove failed", detail=repr(exc))]
            )

    # ----------------------------------------------------------------------- fonts (§4.3)
    def list_fonts(self) -> FontListReport:
        """List every resolvable font family, bundled or installed (spec §4.3). Never raises."""
        if self._fonts is None:  # pragma: no cover - always wired in production
            return FontListReport(ok=False, install_dir="", diagnostics=[_unwired("fonts")])
        try:
            return self._fonts.list_fonts()
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return FontListReport(
                ok=False,
                install_dir="",
                diagnostics=[internal_error("font list failed", detail=repr(exc))],
            )

    def add_font(self, source: Path, license_path: Path | None = None) -> FontActionReport:
        """Install a font into the Arcavex home and report its resolved family. Never raises."""
        if self._fonts is None:  # pragma: no cover - always wired in production
            return FontActionReport(ok=False, diagnostics=[_unwired("fonts")])
        try:
            return self._fonts.add_font(
                Path(source), None if license_path is None else Path(license_path)
            )
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return FontActionReport(
                ok=False, diagnostics=[internal_error("font add failed", detail=repr(exc))]
            )

    def remove_font(self, family: str) -> FontActionReport:
        """Remove an installed font family; a bundled family is refused. Never raises."""
        if self._fonts is None:  # pragma: no cover - always wired in production
            return FontActionReport(ok=False, diagnostics=[_unwired("fonts")])
        try:
            return self._fonts.remove_font(family)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return FontActionReport(
                ok=False, diagnostics=[internal_error("font remove failed", detail=repr(exc))]
            )

    # ----------------------------------------------------------------------- skill install
    def list_skill_targets(
        self, path: Path | None = None, project: bool = False
    ) -> SkillInstallReport:
        """List every destination the bundled design skill can install to. Never raises."""
        if self._skills is None:  # pragma: no cover - always wired in production
            return SkillInstallReport(
                ok=False, skill="", source="", diagnostics=[_unwired("skills")]
            )
        try:
            return self._skills.list_targets(
                None if path is None else Path(path), project=project
            )
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return SkillInstallReport(
                ok=False,
                skill="",
                source="",
                diagnostics=[internal_error("skill list failed", detail=repr(exc))],
            )

    def install_skill(
        self,
        targets: list[str] | None = None,
        path: Path | None = None,
        force: bool = False,
        project: bool = False,
    ) -> SkillInstallReport:
        """Install the bundled design skill into one or more harnesses. Never raises."""
        if self._skills is None:  # pragma: no cover - always wired in production
            return SkillInstallReport(
                ok=False, skill="", source="", diagnostics=[_unwired("skills")]
            )
        try:
            return self._skills.install(
                targets=targets,
                path=None if path is None else Path(path),
                force=force,
                project=project,
            )
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return SkillInstallReport(
                ok=False,
                skill="",
                source="",
                diagnostics=[internal_error("skill install failed", detail=repr(exc))],
            )

    # ------------------------------------------------------------------------ mcp install
    def list_mcp_targets(self, command: Path | None = None) -> McpInstallReport:
        """Describe every AI host the MCP server can be registered with. Never raises."""
        if self._mcp_hosts is None:  # pragma: no cover - always wired in production
            return McpInstallReport(ok=False, diagnostics=[_unwired("mcp hosts")])
        try:
            return self._mcp_hosts.list_targets(
                command=None if command is None else Path(command)
            )
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return McpInstallReport(
                ok=False,
                diagnostics=[internal_error("mcp target list failed", detail=repr(exc))],
            )

    def install_mcp(
        self,
        targets: list[str] | None = None,
        command: Path | None = None,
        force: bool = False,
    ) -> McpInstallReport:
        """Register the MCP server with one or more AI hosts. Never raises."""
        if self._mcp_hosts is None:  # pragma: no cover - always wired in production
            return McpInstallReport(ok=False, diagnostics=[_unwired("mcp hosts")])
        try:
            return self._mcp_hosts.install(
                targets=targets,
                command=None if command is None else Path(command),
                force=force,
            )
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return McpInstallReport(
                ok=False,
                diagnostics=[internal_error("mcp install failed", detail=repr(exc))],
            )

    def scaffold_template(
        self, name: str, target: Path, formats: list[str] | None = None
    ) -> ScaffoldResult:
        """Scaffold a new renderable one-file template directory. Never raises.

        ``formats`` names the canvas presets to declare (``square``, ``story``, ``portrait``,
        ``landscape``, ``a4``, ``a3``, ``a2``, ``letter``, ``tabloid``); the default is
        square + story. An unknown preset is a located ``ARC-TPL-072`` listing them.
        """
        if self._authoring is None:  # pragma: no cover - always wired in production
            return ScaffoldResult(ok=False, diagnostics=[_unwired("authoring")])
        try:
            return self._authoring.scaffold(name, Path(target), formats)
        except DiagnosticError as exc:
            return ScaffoldResult(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return ScaffoldResult(
                ok=False, diagnostics=[internal_error("Scaffold failed", detail=repr(exc))]
            )

    def check_template(
        self,
        template: Path,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> CheckResult:
        """Validate a template without data (schema + structure + preview_data)."""
        diagnostics = self.validate_template(
            template, data=None, format_name=format_name, locale=locale, style=style
        )
        return CheckResult(ok=not has_errors(diagnostics), diagnostics=diagnostics)

    def inspect_template(self, template: Path) -> TemplateInspectReport:
        """Inspect a template's contract. Never raises."""
        if self._authoring is None:  # pragma: no cover - always wired in production
            return TemplateInspectReport(ok=False, diagnostics=[_unwired("authoring")])
        try:
            return self._authoring.inspect(Path(template))
        except DiagnosticError as exc:
            return TemplateInspectReport(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return TemplateInspectReport(
                ok=False, diagnostics=[internal_error("Inspect failed", detail=repr(exc))]
            )

    def inspect_resolved(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
    ) -> TemplateResolvedReport:
        """Report final layered values and their originating layers (--resolved). Never raises."""
        try:
            result = self._compiler.inspect_resolved(template, data, format_name, locale)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return TemplateResolvedReport(
                ok=False, diagnostics=[internal_error("Resolve inspect failed", detail=repr(exc))]
            )
        return TemplateResolvedReport(
            ok=result.ok,
            format=result.format_name,
            locale=result.locale,
            direction=result.direction,
            digits=result.digits,
            style=result.style,
            patches=[
                ResolvedPatchInfo(
                    layer=p.layer, op=p.op, path=p.path, value=p.value, effective=p.effective
                )
                for p in result.patches
            ],
            diagnostics=result.diagnostics,
        )

    def split_template(self, template: Path) -> SplitResult:
        """Convert a one-file template into a split directory losslessly. Never raises."""
        if self._authoring is None:  # pragma: no cover - always wired in production
            return SplitResult(ok=False, diagnostics=[_unwired("authoring")])
        try:
            return self._authoring.split(Path(template))
        except DiagnosticError as exc:
            return SplitResult(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return SplitResult(
                ok=False, diagnostics=[internal_error("Split failed", detail=repr(exc))]
            )

    def patch_template(
        self, template: Path, ops: list[PatchOp], base_sha256: str | None = None
    ) -> PatchTemplateResult:
        """Apply path-addressed patch ops to a template file on disk (§3.7, §4.1.4). Never raises.

        The mutation contract for an AI author: each op addresses a stable authored node id, the
        file is round-tripped through ruamel so comments survive, and an unknown path is a
        located ``ARC-TPL-092`` rather than a silent no-op. When ``base_sha256`` is given and no
        longer matches the file on disk the patch is refused (``ARC-TPL-110``) so a concurrent
        edit is never clobbered (§8.3). Reachable via CLI/API, so MCP adds no exclusive power.
        """
        if self._authoring is None:  # pragma: no cover - always wired in production
            return PatchTemplateResult(ok=False, diagnostics=[_unwired("authoring")])
        try:
            return self._authoring.patch_template(Path(template), ops, base_sha256)
        except DiagnosticError as exc:
            return PatchTemplateResult(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return PatchTemplateResult(
                ok=False, diagnostics=[internal_error("Patch failed", detail=repr(exc))]
            )

    # -------------------------------------------------------------------- preview
    def preview_path(
        self,
        template: Path,
        format_name: str,
        *,
        data: Path | None = None,
        locale: str | None = None,
        dpi: int | None = None,
        style: str | None = None,
    ) -> Path:
        """Return the stable preview output path for a template + format and its variant inputs.

        The path is derived from the resolved ``template.yaml`` so the same template always
        previews to the same file regardless of whether the caller passed the directory or the
        file (§4.1.1 path equivalence, CR-4), under ``$ARCAVEX_HOME/cache/preview`` or an OS
        temp directory.

        Every other input that changes the pixels — the data file, the locale, the DPI, the style
        pack — takes part in the name when it is given, so two variants of one template previewed
        side by side land in two files instead of taking turns overwriting one. The same inputs
        always give the same path (``--watch`` and the desktop re-read one file across renders),
        and with none of them given the historical template + format path is unchanged, so
        existing callers keep the file they are already watching.
        """
        try:
            _root_dir, template_yaml = self._compiler.resolve_paths(template)
            base = template_yaml
        except Exception:  # noqa: BLE001 - fall back to the raw path when resolution fails
            base = Path(template)
        key_source = str(base.resolve())
        variant = _preview_variant(data, locale, dpi, style)
        if variant:
            key_source += "\n" + variant
        key = hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:16]
        # The locale is short and already file-safe (project previews name it the same way), so
        # it is spelled out too: a person looking at the cache can tell the ``fa`` preview apart.
        segment = f".{locale}" if locale else ""
        root = self._resolve_preview_root()
        return root / f"{key}.{format_name}{segment}.png"

    def render_preview(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
        dpi: int | None = None,
        changed_file: str | None = None,
        debug: bool = False,
    ) -> PreviewResult:
        """Render to the stable preview path atomically, with compile/render timings.

        Never raises and never creates a recorded run. On failure the previous preview file is
        left untouched (the atomic temp+replace only runs on success), so a viewer keeps the
        last good image (spec §6.3). With ``debug`` the preview carries the layout overlay.
        """
        try:
            return self._render_preview_inner(
                template, data, format_name, locale, style, dpi, changed_file, debug
            )
        except DiagnosticError as exc:
            return PreviewResult(
                ok=False, changed_file=changed_file, diagnostics=list(exc.diagnostics)
            )
        except Exception:  # noqa: BLE001 - facade boundary must not leak
            last_line = traceback.format_exc().splitlines()[-1]
            return PreviewResult(
                ok=False,
                changed_file=changed_file,
                diagnostics=[internal_error("Preview failed unexpectedly", detail=last_line)],
            )

    def _render_preview_inner(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        dpi: int | None,
        changed_file: str | None,
        debug: bool = False,
    ) -> PreviewResult:
        compile_start = time.perf_counter()
        compiled = self._compiler.compile(template, data, format_name, locale, style)
        compile_ms = (time.perf_counter() - compile_start) * 1000.0
        diagnostics = list(compiled.diagnostics)
        inferred = dict(compiled.inferred)
        if compiled.document is None or has_errors(diagnostics):
            return PreviewResult(
                ok=False,
                changed_file=changed_file,
                compile_ms=compile_ms,
                inferred=inferred,
                diagnostics=diagnostics,
            )

        resolved_format = compiled.format_name or "out"
        out_path = self.preview_path(
            template, resolved_format, data=data, locale=locale, dpi=dpi, style=style
        )

        render_start = time.perf_counter()
        surface, _, warnings = self._layout_and_render(compiled.document, dpi, debug=debug)
        diagnostics.extend(warnings)
        report = self._export_replace(surface, out_path, dpi)
        render_ms = (time.perf_counter() - render_start) * 1000.0

        return PreviewResult(
            ok=True,
            output_path=str(out_path),
            changed_file=changed_file,
            compile_ms=compile_ms,
            render_ms=render_ms,
            content_sha256=report.content_sha256,
            inferred=inferred,
            diagnostics=diagnostics,
        )

    def collect_asset_paths(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
    ) -> list[str]:
        """Return the resolved image-asset paths a template references (best effort, CR-9).

        Used by watch mode to also observe out-of-tree assets. Never raises: on any compile
        failure it returns an empty list, so watching degrades gracefully.
        """
        try:
            compiled = self._compiler.compile(template, data, format_name, locale, style)
        except Exception:  # noqa: BLE001 - best-effort asset discovery must not crash watch
            return []
        if compiled.document is None:
            return []
        out: list[str] = []

        def visit(node: CompiledNode) -> None:
            if isinstance(node, CompiledImage):
                out.append(node.asset_path)
            if isinstance(node, CompiledGroup):
                for child in node.children:
                    visit(child)

        visit(compiled.document.root)
        return out

    # ---------------------------------------------------------- projects & provenance (§5)
    def create_project(
        self,
        target: Path,
        name: str,
        template_ref: str,
        style: str | None = None,
        formats: list[str] | None = None,
        locales: list[str] | None = None,
    ) -> ProjectResult:
        """Scaffold a project pinning ``template_ref``. Never raises."""
        return self._guard_project(
            lambda o: o.create_project(Path(target), name, template_ref, style, formats, locales),
            ProjectResult,
        )

    def project_status(
        self, start: Path | None = None, project: Path | None = None
    ) -> ProjectStatusReport:
        """Resolve and report the active project (cwd walk or ``--project``). Never raises."""
        return self._guard_project(
            lambda o: o.project_status(start, project), ProjectStatusReport
        )

    def project_snapshot(
        self, start: Path | None = None, project: Path | None = None
    ) -> ProjectSnapshotReport:
        """Return a read-only project snapshot and independent revision manifests."""
        capabilities = list(self.engine_handshake().capabilities)
        return self._guard_project(
            lambda o: o.project_snapshot(start, project, capabilities),
            ProjectSnapshotReport,
        )

    def layer_tree(
        self,
        project: Path | None = None,
        *,
        mode: Literal["authored", "rendered"] = "authored",
        format_name: str | None = None,
        locale: str | None = None,
        start: Path | None = None,
    ) -> LayerTreeReport:
        """Return the engine-owned definition or rendered layer hierarchy."""
        resolved_project = None if project is None else Path(project)
        return self._guard_project(
            lambda orchestrator: orchestrator.layer_tree(
                start, resolved_project, mode, format_name, locale
            ),
            LayerTreeReport,
        )

    def hit_test(
        self,
        project: Path | None = None,
        *,
        x_pt: float | str,
        y_pt: float | str,
        format_name: str | None = None,
        locale: str | None = None,
        start: Path | None = None,
    ) -> HitTestReport:
        """Hit-test one canonical canvas-point coordinate against rendered paint bounds."""
        resolved_project = None if project is None else Path(project)
        return self._guard_project(
            lambda orchestrator: orchestrator.hit_test(
                start,
                resolved_project,
                _hit_point(x_pt, y_pt),
                format_name,
                locale,
            ),
            HitTestReport,
        )

    def project_ui_metadata(
        self, start: Path | None = None, project: Path | None = None
    ) -> ProjectUIMetadataReport:
        """Read optional project editor metadata without creating its sidecar."""
        return self._guard_project(
            lambda o: o.project_ui_metadata(start, project), ProjectUIMetadataReport
        )

    def set_project_ui_metadata(
        self,
        metadata: ProjectUIMetadata,
        start: Path | None = None,
        project: Path | None = None,
    ) -> ProjectUIMetadataReport:
        """Atomically replace validated project editor metadata."""
        return self._guard_project(
            lambda o: o.set_project_ui_metadata(start, project, metadata),
            ProjectUIMetadataReport,
        )

    def project_policy(
        self, start: Path | None = None, project: Path | None = None
    ) -> ProjectPolicyReport:
        """Return effective automation and extension policy without writing defaults."""
        return self._guard_project(
            lambda o: o.project_policy(start, project), ProjectPolicyReport
        )

    def set_project_policy(
        self,
        mode: AutomationMode,
        extensions: ExtensionMode,
        start: Path | None = None,
        project: Path | None = None,
    ) -> ProjectPolicyReport:
        """Atomically update project automation and extension policy."""
        return self._guard_project(
            lambda o: o.set_project_policy(start, project, mode, extensions),
            ProjectPolicyReport,
        )

    def list_project_proposals(
        self, start: Path | None = None, project: Path | None = None
    ) -> ProposalListReport:
        """List valid project queue records and diagnostics for malformed entries."""
        return self._guard_project(
            lambda o: o.list_project_proposals(start, project), ProposalListReport
        )

    def approve_project_proposal(
        self,
        command_id: str,
        start: Path | None = None,
        project: Path | None = None,
    ) -> ProposalActionReport:
        """Revision-check and authorize a proposal without applying its command."""
        return self._guard_project(
            lambda o: o.approve_project_proposal(start, project, command_id),
            ProposalActionReport,
        )

    def reject_project_proposal(
        self,
        command_id: str,
        reason: str,
        start: Path | None = None,
        project: Path | None = None,
    ) -> ProposalActionReport:
        """Persist an explicit rejection while retaining the proposal record."""
        return self._guard_project(
            lambda o: o.reject_project_proposal(start, project, command_id, reason),
            ProposalActionReport,
        )

    def clone_project(
        self,
        target: Path,
        name: str,
        start: Path | None = None,
        project: Path | None = None,
    ) -> ProjectResult:
        """Clone the active project into ``target`` under ``name``. Never raises."""
        return self._guard_project(
            lambda o: o.clone_project(start, project, Path(target), name), ProjectResult
        )

    def set_project_status(
        self, status: str, start: Path | None = None, project: Path | None = None
    ) -> ProjectStatusReport:
        """Set the active project's status. Never raises."""
        return self._guard_project(
            lambda o: o.set_project_status(start, project, status), ProjectStatusReport
        )

    def render_project(
        self,
        start: Path | None = None,
        project: Path | None = None,
        formats: list[str] | None = None,
        locales: list[str] | None = None,
        dpi: int | None = None,
    ) -> RunReport:
        """Render the active project's formats × locales into a recorded run. Never raises."""
        return self._guard_project(
            lambda o: o.render_project(start, project, formats, locales, dpi), RunReport
        )

    def record_render(
        self,
        template: Path,
        data: Path | None = None,
        format_name: str | None = None,
        locale: str | None = None,
        style: str | None = None,
        dpi: int | None = None,
        outputs_root: Path | None = None,
    ) -> RunReport:
        """Direct render with a recorded run manifest (``render --record``). Never raises."""
        return self._guard_project(
            lambda o: o.record_render(
                Path(template), data, format_name, locale, style, dpi, outputs_root
            ),
            RunReport,
        )

    def list_runs(
        self,
        start: Path | None = None,
        project: Path | None = None,
        path: Path | None = None,
    ) -> RunListReport:
        """List recorded runs for the active project, or under an explicit ``path``. Never raises.

        With ``path`` (or when no project is discoverable but a ``./outputs`` directory exists),
        lists direct-mode ``--record`` runs under that directory rather than a project's
        ``outputs/`` — so recorded runs are discoverable outside a project too (DX-7).
        """
        resolved = Path(path) if path is not None else None
        return self._guard_project(
            lambda o: o.list_runs(start, project, resolved), RunListReport
        )

    def validate_project(
        self,
        start: Path | None = None,
        project: Path | None = None,
        formats: list[str] | None = None,
        locales: list[str] | None = None,
    ) -> CheckResult:
        """Validate the discovered project across its formats × locales (DX-1). Never raises.

        Compiles the project's template with its data and override patch for each target and
        exercises layout, the same coverage ``validate`` gives a template, so a project author
        can dry-run before rendering. No project found returns the ``ARC-PRJ-001`` diagnostic.
        """
        if self._orchestrator is None:  # pragma: no cover - always wired in production
            return CheckResult(ok=False, diagnostics=[_unwired("projects")])
        try:
            inputs = self._orchestrator.project_inputs(start, project, formats, locales)
        except DiagnosticError as exc:
            return CheckResult(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return CheckResult(
                ok=False, diagnostics=[internal_error("Project validate failed", detail=repr(exc))]
            )
        diagnostics: list[Diagnostic] = list(inputs.diagnostics)
        for fmt, locale in inputs.targets:
            diagnostics.extend(self._validate_project_target(inputs, fmt, locale))
        diagnostics = _dedupe(diagnostics)
        return CheckResult(ok=not has_errors(diagnostics), diagnostics=diagnostics)

    def _validate_project_target(
        self, inputs: ProjectInputs, format_name: str | None, locale: str | None
    ) -> list[Diagnostic]:
        result = self._compiler.compile(
            inputs.template_dir, inputs.data_path, format_name, locale, inputs.style,
            project_patch=inputs.patch_ops, project_patch_file=inputs.patch_file,
        )
        diagnostics = list(result.diagnostics)
        if result.document is not None and not has_errors(diagnostics):
            diagnostics.extend(self._try_layout(result.document))
        return diagnostics

    def preview_project(
        self,
        start: Path | None = None,
        project: Path | None = None,
        formats: list[str] | None = None,
        locales: list[str] | None = None,
        dpi: int | None = None,
    ) -> PreviewProjectReport:
        """Preview the discovered project's formats × locales to stable paths (DX-1). Never raises.

        Like ``preview`` for a template, but resolves the project's template, data, and override
        patch and writes one stable preview PNG per target. No recorded run is created.
        """
        if self._orchestrator is None:  # pragma: no cover - always wired in production
            return PreviewProjectReport(ok=False, diagnostics=[_unwired("projects")])
        try:
            inputs = self._orchestrator.project_inputs(start, project, formats, locales)
        except DiagnosticError as exc:
            return PreviewProjectReport(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return PreviewProjectReport(
                ok=False, diagnostics=[internal_error("Project preview failed", detail=repr(exc))]
            )
        previews = [
            self._preview_project_target(inputs, fmt, locale, dpi)
            for fmt, locale in inputs.targets
        ]
        return PreviewProjectReport(
            ok=all(p.ok for p in previews),
            previews=previews,
            diagnostics=list(inputs.diagnostics),
        )

    def _preview_project_target(
        self, inputs: ProjectInputs, format_name: str | None, locale: str | None, dpi: int | None
    ) -> PreviewResult:
        try:
            compiled = self._compiler.compile(
                inputs.template_dir, inputs.data_path, format_name, locale, inputs.style,
                project_patch=inputs.patch_ops, project_patch_file=inputs.patch_file,
            )
        except DiagnosticError as exc:
            return PreviewResult(ok=False, diagnostics=list(exc.diagnostics))
        diagnostics = list(compiled.diagnostics)
        if compiled.document is None or has_errors(diagnostics):
            return PreviewResult(ok=False, diagnostics=diagnostics)
        resolved_format = compiled.format_name or "out"
        key = hashlib.sha256(
            f"{inputs.name}:{inputs.ref}:{resolved_format}:{locale or ''}".encode()
        ).hexdigest()[:16]
        seg = f".{locale}" if locale else ""
        out_path = self._resolve_preview_root() / f"{key}.{resolved_format}{seg}.png"
        try:
            report, warnings = self._render_document(compiled.document, out_path, dpi)
        except DiagnosticError as exc:
            return PreviewResult(ok=False, diagnostics=diagnostics + list(exc.diagnostics))
        diagnostics.extend(warnings)
        return PreviewResult(
            ok=True,
            output_path=str(out_path),
            content_sha256=report.content_sha256,
            inferred=dict(compiled.inferred),
            diagnostics=diagnostics,
        )

    def _render_document(
        self, document: CompiledDocument, out_path: Path, dpi: int | None
    ) -> tuple[Any, list[Diagnostic]]:
        """Lay out, render, and atomically export a compiled document to ``out_path``."""
        surface, _, warnings = self._layout_and_render(document, dpi)
        return self._export_replace(surface, out_path, dpi), warnings

    def rerun(self, run_dir: Path) -> RerunReport:
        """Reproduce a recorded run into a new run dir (byte-identical on match). Never raises."""
        return self._guard_project(lambda o: o.rerun(Path(run_dir)), RerunReport)

    def diff_runs(self, run_a: Path, run_b: Path) -> DiffReport:
        """Diff two recorded runs (pixel/perceptual + metadata). Never raises."""
        return self._guard_project(
            lambda o: o.diff(Path(run_a), Path(run_b)), DiffReport
        )

    def batch_render(
        self, globs: list[str], jobs: int = 1, dpi: int | None = None
    ) -> BatchReport:
        """Render every project matched by ``globs`` in parallel jobs (== serial). Never raises."""
        return self._guard_project(lambda o: o.batch_render(globs, jobs, dpi), BatchReport)

    def upgrade_project(
        self,
        to_version: str,
        apply: bool = False,
        start: Path | None = None,
        project: Path | None = None,
    ) -> UpgradeReport:
        """Preview a template-version upgrade; update the pin only when ``apply``. Never raises."""
        return self._guard_project(
            lambda o: o.upgrade_project(start, project, to_version, apply), UpgradeReport
        )

    def publish_template(
        self, template: Path, name: str, version: str, set_default: bool = True
    ) -> PublishReport:
        """Publish a template directory into the library as an immutable version. Never raises."""
        return self._guard_project(
            lambda o: o.publish_template(Path(template), name, version, set_default),
            PublishReport,
        )

    def detach_template(
        self, start: Path | None = None, project: Path | None = None
    ) -> DetachReport:
        """Copy the project's library template into the project (upgrades off). Never raises."""
        return self._guard_project(lambda o: o.detach_template(start, project), DetachReport)

    # ------------------------------------------------------------------ data & assets (§4.7)
    def set_data(
        self,
        keypath: str,
        value: Any,
        start: Path | None = None,
        project: Path | None = None,
    ) -> DataReport:
        """Set a single value at ``keypath`` in the active project's data (§3.7). Never raises.

        Writes the value into the project's base data document (creating intermediate mappings),
        then compiles the project so the returned diagnostics report whether the change still
        validates — the located feedback an author (human or AI) needs to self-correct.
        """
        return self._guard_project(
            lambda o: o.set_data(start, project, keypath, value), DataReport
        )

    def import_data(
        self,
        yaml_text: str,
        locale: str | None = None,
        start: Path | None = None,
        project: Path | None = None,
    ) -> DataReport:
        """Merge a YAML data document into the active project's data (§3.7). Never raises.

        Uses the data-overlay merge semantics (mappings merge, scalars/lists replace, ``!delete``
        removes) and revalidates. ``locale`` selects the template locale to compile-validate
        against after the merge, so an author can check the merged data under a specific locale.
        """
        return self._guard_project(
            lambda o: o.import_data(start, project, yaml_text, locale), DataReport
        )

    def add_asset(
        self, source: Path, start: Path | None = None, project: Path | None = None
    ) -> AssetReport:
        """Ingest an image into the workspace CAS and return its reference (§4.7). Never raises.

        Ingestion enforces the decode guards against the file header before any decode; the same
        content always resolves to the same hash, so this is the ingest step a template
        expression's asset reference and a run manifest both rely on.
        """
        return self._guard_project(
            lambda o: o.add_asset(start, project, Path(source)), AssetReport
        )

    def annotate_asset(self, sha256: str, annotations: dict[str, Any]) -> AssetReport:
        """Write sidecar annotations onto an ingested asset (§4.7). Never raises.

        Annotations (facing/focal_point/tags) are stored at ingest time and consumed by template
        expressions; render-time image analysis stays prohibited, so this is where an AI records
        what it saw after *looking* at the image, once.
        """
        return self._guard_project(
            lambda o: o.annotate_asset(sha256, annotations), AssetReport
        )

    def list_templates(self) -> TemplateListReport:
        """List every published library template and its versions (§5.1). Never raises."""
        return self._guard_project(lambda o: o.list_templates(), TemplateListReport)

    def list_projects(self, root: Path | None = None) -> ProjectListReport:
        """List projects discovered under ``root`` (default cwd). Never raises."""
        resolved = Path(root) if root is not None else None
        return self._guard_project(lambda o: o.list_projects(resolved), ProjectListReport)

    def _guard_project(
        self, call: Callable[[OrchestratorProtocol], _ResultT], model: type[_ResultT]
    ) -> _ResultT:
        """Run an orchestrator call at the facade boundary, never leaking an exception."""
        if self._orchestrator is None:  # pragma: no cover - always wired in production
            return model(ok=False, diagnostics=[_unwired("projects")])
        try:
            return call(self._orchestrator)
        except DiagnosticError as exc:
            return model(ok=False, diagnostics=list(exc.diagnostics))
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return model(
                ok=False, diagnostics=[internal_error("Project op failed", detail=repr(exc))]
            )

    def _resolve_preview_root(self) -> Path:
        if self._preview_root is not None:
            return self._preview_root
        home = os.environ.get("ARCAVEX_HOME")
        if home:
            return Path(home) / "cache" / "preview"
        return Path(tempfile.gettempdir()) / "arcavex" / "cache" / "preview"


def _unwired(what: str) -> Diagnostic:
    return internal_error(f"{what} service is not wired")


def param_infos(schema: type[BaseModel]) -> list[EffectParamInfo]:
    """Project a pydantic component param schema onto reportable field infos (DX-6).

    Shared by ``effects list``, ``shapes list``, and the compiler's ``ARC-FX-912`` hint, so a
    parameter is described the same way wherever an author meets it. Type names are
    author-facing: a length param (points/mm/px) reports ``length`` and a colour param reports
    ``colour``, detected from the field's ``BeforeValidator`` rather than a raw
    ``number``/``array`` so the discovery output tells an author what unit grammar to use.
    """
    out: list[EffectParamInfo] = []
    for name, finfo in schema.model_fields.items():
        out.append(
            EffectParamInfo(
                name=name,
                type=_friendly_param_type(finfo),
                required=finfo.is_required(),
                default=None if finfo.is_required() else _plain_default(finfo.default),
                constraint=_param_constraint(finfo),
            )
        )
    return out


def _friendly_param_type(finfo: Any) -> str:
    """Return an author-facing type name for a pydantic field (kernel stays builtin-free)."""
    for meta in finfo.metadata:
        func = getattr(meta, "func", None)
        fname = getattr(func, "__name__", "") if func is not None else ""
        if fname == "_as_pt":
            return "length"
        if fname == "_as_rgba":
            return "colour"
    annotation = finfo.annotation
    mapping: dict[Any, str] = {float: "number", int: "integer", bool: "boolean", str: "string"}
    if annotation in mapping:
        return mapping[annotation]
    origin = getattr(annotation, "__origin__", None)
    if origin in (tuple, list):
        return "list"
    return getattr(annotation, "__name__", str(annotation))


def _param_constraint(finfo: Any) -> str | None:
    """Render a field's numeric bounds (ge/gt/le/lt) as a short ``lo..hi`` string, if any."""
    lo: str | None = None
    hi: str | None = None
    for meta in finfo.metadata:
        if hasattr(meta, "ge"):
            lo = f">={meta.ge:g}"
        elif hasattr(meta, "gt"):
            lo = f">{meta.gt:g}"
        if hasattr(meta, "le"):
            hi = f"<={meta.le:g}"
        elif hasattr(meta, "lt"):
            hi = f"<{meta.lt:g}"
    parts = [p for p in (lo, hi) if p is not None]
    return ", ".join(parts) if parts else None


def _plain_default(value: Any) -> Any:
    """Return a JSON-friendly form of a field default (tuples become lists)."""
    if isinstance(value, tuple):
        return list(value)
    return value


def _first_doc_line(doc: str | None) -> str | None:
    """The first line of a docstring, as a component's one-line description."""
    if not doc:
        return None
    lines = [line.strip() for line in doc.strip().splitlines()]
    return lines[0] if lines and lines[0] else None


def _style_summary(pack: StylePackProtocol) -> StyleSummary:
    """Project a loaded style pack onto the reportable summary model."""
    return StyleSummary(
        name=pack.name,
        version=pack.version,
        palettes=dict(pack.palettes),
        fonts=dict(pack.fonts),
        effect_presets=dict(pack.effect_presets),
        shape_presets=dict(pack.shape_presets),
        roles=dict(pack.roles),
    )


# --------------------------------------------------------------- layout report builders
def _logical_edge(edge: str, direction: str) -> str:
    if edge == "start":
        return "left" if direction == "ltr" else "right"
    if edge == "end":
        return "right" if direction == "ltr" else "left"
    return edge


def _edge_value(edge: str, node: LayoutNode) -> float:
    b = node.bounds
    return {
        "top": b.y, "bottom": b.bottom, "center_y": b.center_y,
        "left": b.x, "right": b.right, "center_x": b.center_x,
    }[edge]


def _canvas_bounds(node: LayoutNode) -> Rect:
    """Return cumulative canvas geometry, with compatibility for legacy solvers."""
    return node.canvas_bounds or node.bounds


def _canvas_paint_bounds(node: LayoutNode) -> Rect:
    """Return cumulative effect-grown geometry, with compatibility for legacy solvers."""
    return node.canvas_paint_bounds or node.paint_bounds


def _build_node_report(
    compiled: CompiledNode,
    layout: LayoutNode,
    group_dir: str,
    dpi: int,
    overlaps: list[SiblingOverlap],
    parent_stack: str | None = None,
) -> LayoutNodeReport:
    # Desktop layout inspection and layer selection share cumulative canvas-space geometry.
    # Third-party/legacy solvers may omit the excluded provenance fields, so retain the
    # pre-ancestor values only as a compatibility fallback.
    b = _canvas_bounds(layout)
    pb = _canvas_paint_bounds(layout)
    scale = dpi / 72.0
    overflow = None
    if layout.overflow.kind != "none" or layout.overflow.measured_h_pt > 0.0:
        overflow = OverflowReport(
            kind=layout.overflow.kind,
            measured_w_pt=layout.overflow.measured_w_pt,
            measured_h_pt=layout.overflow.measured_h_pt,
            box_w_pt=layout.overflow.box_w_pt,
            box_h_pt=layout.overflow.box_h_pt,
            base_size_pt=layout.overflow.base_size_pt,
            resolved_size_pt=layout.overflow.resolved_size_pt,
        )
    anchors = _derive_anchors(compiled, layout, group_dir, parent_stack)

    children_reports: list[LayoutNodeReport] = []
    if isinstance(compiled, CompiledGroup):
        by_id = {c.source_node_id: c for c in layout.children}
        stack_kind = compiled.stack.kind if compiled.stack.kind != "absolute" else None
        for child in compiled.children:
            lchild = by_id.get(child.id)
            if lchild is None:
                continue
            children_reports.append(
                _build_node_report(child, lchild, compiled.direction, dpi, overlaps, stack_kind)
            )
        _collect_overlaps(layout.children, overlaps, _canvas_bounds(layout))

    t = layout.absolute_transform
    return LayoutNodeReport(
        id=layout.source_node_id,
        kind=layout.kind,
        bounds_pt=(b.x, b.y, b.w, b.h),
        bounds_px=(b.x * scale, b.y * scale, b.w * scale, b.h * scale),
        paint_bounds_pt=(pb.x, pb.y, pb.w, pb.h),
        paint_bounds_px=(pb.x * scale, pb.y * scale, pb.w * scale, pb.h * scale),
        absolute_transform=(t.a, t.b, t.c, t.d, t.e, t.f),
        rotate_deg=layout.rotate_deg,
        overflow=overflow,
        anchors=anchors,
        children=children_reports,
    )


def _derive_anchors(
    compiled: CompiledNode, layout: LayoutNode, group_dir: str, parent_stack: str | None
) -> list[AnchorDerivation]:
    if parent_stack is not None and not compiled.constraints.anchors:
        return [
            AnchorDerivation(
                axis="horizontal", edge="—",
                expression=f"positioned by {parent_stack}", resolved_pt=layout.bounds.x,
            ),
            AnchorDerivation(
                axis="vertical", edge="—",
                expression=f"positioned by {parent_stack}", resolved_pt=layout.bounds.y,
            ),
        ]
    out: list[AnchorDerivation] = []
    horizontal = {"left", "right", "center_x"}
    for key, anchor in compiled.constraints.anchors.items():
        phys_key = _logical_edge(key, group_dir)
        axis = "horizontal" if phys_key in horizontal else "vertical"
        ref_edge = _logical_edge(anchor.edge, group_dir)
        # A logical (start/end) reference edge takes its offset in reading order, which the
        # solver flips to -offset under rtl; the printed expression must reflect that flipped
        # math so the derivation string evaluates to the resolved value (CR-7).
        display_offset = anchor.offset_pt
        if anchor.edge in ("start", "end") and group_dir == "rtl":
            display_offset = -display_offset
        sign = "+" if display_offset >= 0 else "-"
        offset = f" {sign} {abs(display_offset):g}pt" if display_offset else ""
        expression = f"{anchor.ref}.{ref_edge}{offset}"
        out.append(
            AnchorDerivation(
                axis=axis, edge=phys_key, expression=expression,
                resolved_pt=_edge_value(phys_key, layout),
            )
        )
    return out


def _content_aabb(node: LayoutNode) -> Rect:
    """Return the node's ink footprint: its layout ``bounds`` AABB, without effect growth.

    ``paint_bounds`` folds two unrelated expansions together — the post-rotation AABB, which is
    real geometry the node occupies, and the effects' declared bounds expansion, which is only
    an allocation request so a blur or tear is not clipped. Collision reporting needs the first
    without the second, otherwise a drop-shadow reads as a collision.

    Rotated nodes still contribute their post-transform AABB, matching what siblings anchor to
    (CR-14); the AABB of a rotated node is coarser than its ink, which is why such a pair is
    reported as ``content`` and left to the author to judge.
    """
    if node.canvas_bounds is not None:
        # The solver has already projected the unexpanded layout rectangle through every
        # ancestor transform. This is exactly the content footprint: cumulative, but without
        # effect growth. Re-transforming it here would apply ancestor rotations twice.
        return node.canvas_bounds
    if node.render_bounds == node.bounds:
        # Nothing grew the box, so paint_bounds already *is* the content AABB. Reusing it keeps
        # the solver's 1/1024pt geometry quantization intact instead of re-deriving a rect that
        # differs from it in the last decimal.
        return node.paint_bounds
    if not node.rotate_deg:
        return node.bounds
    b, m = node.bounds, node.absolute_transform
    corners = [
        m.apply(b.x, b.y), m.apply(b.right, b.y),
        m.apply(b.right, b.bottom), m.apply(b.x, b.bottom),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _collision_rects(node: LayoutNode) -> tuple[Rect, Rect]:
    """The ``(content, paint)`` boxes a node's ink and effects can occupy.

    ``content`` is ``_content_aabb``, narrowed for text to the shaped width. The solver records
    the widest line's advance width in ``overflow.measured_w_pt`` and the renderer places the
    paragraph inside its box by the paragraph alignment, so for an unrotated, unscaled text node
    the horizontal extent of the painted glyphs is known without another measurement pass: a
    short centred word does not reach its box's ends. That extent is the advance width, which
    glyph ink can exceed by a side bearing or an italic overhang — about a point, the ``touch``
    depth. The height stays the line box: nothing measures glyph ink vertically, so a font's
    leading (Lalezar's line box is ~1.57x its size) still counts as content. A rotated or scaled
    node keeps its AABB, because the alignment offset is not an axis-aligned quantity there.

    ``paint`` is the effect-grown box. When the content box was narrowed, the same per-side
    growth is applied to the narrowed box: a glow surrounds the word, not the empty ends of its
    box, and without this a plain text node would report a ``halo`` against whatever sits under
    those ends.
    """
    content = _content_aabb(node)
    paint = _canvas_paint_bounds(node)
    narrowed = _text_extent(node, content)
    if narrowed is None:
        return content, paint
    grown = Rect(
        narrowed.x - (content.x - paint.x),
        narrowed.y - (content.y - paint.y),
        narrowed.w + (paint.w - content.w),
        narrowed.h + (paint.h - content.h),
    )
    return narrowed, grown


def _text_extent(node: LayoutNode, rect: Rect) -> Rect | None:
    """``rect`` narrowed to the node's shaped text width, or ``None`` when that is not known."""
    text = node.resolved_content
    if not isinstance(text, ResolvedText):
        return None
    width = node.overflow.measured_w_pt
    if width <= 0.0 or width >= rect.w - _GEOMETRY_EPS_PT:
        return None
    if not _is_translation(node.absolute_transform):
        return None
    align = _physical_align(text.align, text.direction)
    if align == "left":
        offset = 0.0
    elif align == "right":
        offset = rect.w - width
    else:
        offset = (rect.w - width) / 2.0
    return Rect(rect.x + offset, rect.y, width, rect.h)


def _is_translation(m: Matrix3) -> bool:
    """Whether the affine map moves points without rotating, scaling or shearing them."""
    eps = 1e-9
    return (
        abs(m.a - 1.0) <= eps and abs(m.b) <= eps and abs(m.c) <= eps and abs(m.d - 1.0) <= eps
    )


def _physical_align(align: str, direction: str) -> str:
    """Resolve a logical ``start``/``end`` alignment to a side, as the text service lays it out."""
    if align in ("left", "right", "center"):
        return align
    if align == "end":
        return "left" if direction == "rtl" else "right"
    return "right" if direction == "rtl" else "left"


def _classify_overlap(
    ca: Rect, cb: Rect, pa: Rect, pb: Rect
) -> tuple[OverlapKind, tuple[float, float, float, float]] | None:
    """Classify a sibling pair from its collision and paint rects, or ``None`` if they clear.

    Content wins when the ink footprints themselves intersect, and the rect reported is then the
    content intersection — so the number an author reads is the real collision depth rather than
    a blur radius; an intersection too shallow or too small to be a collision is a ``touch``.
    Otherwise only the effect-grown boxes touch, which is spill.
    """
    content = _intersection(ca, cb)
    if content is not None:
        return ("touch" if _is_touch(content, ca, cb) else "content"), content
    halo = _intersection(pa, pb)
    if halo is not None:
        return "halo", halo
    return None


def _is_touch(inter: tuple[float, float, float, float], ca: Rect, cb: Rect) -> bool:
    """Whether an intersection is a graze: ≤1pt on its short side, or <2% of the smaller box."""
    _, _, w, h = inter
    if min(w, h) <= _TOUCH_MAX_DEPTH_PT + _GEOMETRY_EPS_PT:
        return True
    smaller = min(ca.w * ca.h, cb.w * cb.h)
    return smaller > 0.0 and w * h < _TOUCH_MAX_AREA_FRACTION * smaller


def _collect_overlaps(
    children: tuple[LayoutNode, ...], overlaps: list[SiblingOverlap], region: object
) -> None:
    # ``children`` is in paint order (document order broken by ``z``), so in every pair below
    # ``a`` is painted beneath ``b``.
    visible = [(c, *_collision_rects(c)) for c in children if c.visible]
    for i in range(len(visible)):
        for j in range(i + 1, len(visible)):
            (a, ca, pa), (b, cb, pb) = visible[i], visible[j]
            classified = _classify_overlap(ca, cb, pa, pb)
            if classified is None:
                continue
            # DX-8/RR2-9/BX-42: containment is suppressed as noise only when the *container* is
            # structure — a backdrop, a stroke-only frame, or a filled plate painted beneath the
            # node. A filled shape that fully covers a sibling painted before it hides that
            # sibling, which is a genuine bug and is still reported.
            if _contains(ca, cb) and _is_structure(a, ca, region, beneath=True):
                continue
            if _contains(cb, ca) and _is_structure(b, cb, region, beneath=False):
                continue
            kind, rect = classified
            overlaps.append(
                SiblingOverlap(a=a.source_node_id, b=b.source_node_id, rect_pt=rect, kind=kind)
            )


def _is_structure(node: LayoutNode, content: Rect, region: object, *, beneath: bool) -> bool:
    """Whether ``node``, which fully contains a sibling, is that sibling's structure.

    Three containers legitimately enclose a sibling: a backdrop (``_is_backdrop``: a group, or a
    leaf covering nearly the whole parent region); a stroke-only frame, whose fill is absent or
    transparent so its only ink is the outline drawn *around* the sibling; and a filled plate
    painted ``beneath`` the sibling — a card or a label panel. A plate painted over the sibling
    hides it, so that pair stays a reported collision. Containment is judged on boxes: a circle
    or generator outline that reaches inside its box is not modelled, the same limitation as a
    rotated node's AABB.
    """
    if _is_backdrop(node, content, region):
        return True
    shape = node.resolved_content
    if not isinstance(shape, ResolvedShape):
        return False
    return beneath or not _has_fill(shape)


def _has_fill(shape: ResolvedShape) -> bool:
    """Whether the shape paints an interior: a fill that is present and not fully transparent.

    ``fill: none``/``transparent`` and an explicit zero alpha all arrive here as ``None`` or an
    RGBA with alpha 0, so a stroke-only frame is recognised however it was spelled.
    """
    return shape.fill is not None and shape.fill[3] > 0.0


def _is_backdrop(node: LayoutNode, content: Rect, region: object) -> bool:
    """Whether ``node`` is a backdrop-like container within ``region`` (full-bleed or a group).

    Groups are structural containers, not collisions; a leaf that covers nearly the whole parent
    region is a background. Either legitimately encloses siblings, so their containment is not
    reported as an overlap bug. The test reads ``content`` rather than ``paint_bounds`` so a
    generous shadow cannot promote an ordinary node into a backdrop.
    """
    if node.kind == "group":
        return True
    rw, rh = region.w, region.h  # type: ignore[attr-defined]
    region_area = rw * rh
    if region_area <= 0:
        return False
    return bool((content.w * content.h) >= _BACKDROP_AREA_FRACTION * region_area)


def _contains(outer: object, inner: object) -> bool:
    """Whether ``outer`` fully contains ``inner``, within the geometry tolerance."""
    ox, oy, ow, oh = outer.x, outer.y, outer.w, outer.h  # type: ignore[attr-defined]
    ix, iy, iw, ih = inner.x, inner.y, inner.w, inner.h  # type: ignore[attr-defined]
    eps = _GEOMETRY_EPS_PT
    return bool(
        ox - eps <= ix
        and oy - eps <= iy
        and ox + ow + eps >= ix + iw
        and oy + oh + eps >= iy + ih
    )


def _intersection(a: object, b: object) -> tuple[float, float, float, float] | None:
    ax, ay, aw, ah = a.x, a.y, a.w, a.h  # type: ignore[attr-defined]
    bx, by, bw, bh = b.x, b.y, b.w, b.h  # type: ignore[attr-defined]
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 - x0 > _GEOMETRY_EPS_PT and y1 - y0 > _GEOMETRY_EPS_PT:
        return (x0, y0, x1 - x0, y1 - y0)
    return None


def _coverage_grid(layout: LayoutDocument, cells: int) -> list[list[bool]] | None:
    """Mark a ``cells``x``cells`` grid true wherever a visible leaf node's bounds fall.

    ``None`` when the canvas has no area. A cell is marked if any part of a node touches it, so
    coverage derived from this grid rounds small nodes up to a whole cell.
    """
    w, h = layout.canvas.width_pt, layout.canvas.height_pt
    if w <= 0 or h <= 0:
        return None
    grid = [[False] * cells for _ in range(cells)]

    def mark(node: LayoutNode) -> None:
        if node.children:
            for child in node.children:
                mark(child)
            return
        if not node.visible:
            return
        b = _canvas_bounds(node)
        cx0 = max(0, int(b.x / w * cells))
        cx1 = min(cells, int((b.x + b.w) / w * cells) + 1)
        cy0 = max(0, int(b.y / h * cells))
        cy1 = min(cells, int((b.y + b.h) / h * cells) + 1)
        for cy in range(cy0, cy1):
            for cx in range(cx0, cx1):
                grid[cy][cx] = True

    mark(layout.root)
    return grid


def _covered_fraction(layout: LayoutDocument, cells: int = _COVERAGE_GRID_CELLS) -> float:
    """Approximate the fraction of the canvas covered by any leaf node (coarse grid)."""
    grid = _coverage_grid(layout, cells)
    if grid is None:
        return 0.0
    covered = sum(row.count(True) for row in grid)
    return round(covered / (cells * cells), _COVERAGE_DECIMALS)


def _free_regions(
    layout: LayoutDocument,
    cells: int = _COVERAGE_GRID_CELLS,
    min_rows: int = _MIN_FREE_BAND_ROWS,
) -> list[tuple[float, float, float, float]]:
    """Return maximal full-width empty horizontal bands, largest first (spec §6.1.1).

    Rows of the coverage grid that are entirely uncovered are merged into vertical bands; a band
    is reported when it spans at least ``min_rows`` rows. This is the summary that makes an
    unfilled top/bottom slab obvious.
    """
    w, h = layout.canvas.width_pt, layout.canvas.height_pt
    grid = _coverage_grid(layout, cells)
    if grid is None:
        return []
    empty_rows = [cy for cy in range(cells) if not any(grid[cy])]
    bands: list[tuple[int, int]] = []
    run_start: int | None = None
    prev = -2
    for cy in empty_rows:
        if run_start is None:
            run_start = cy
        elif cy != prev + 1:
            bands.append((run_start, prev))
            run_start = cy
        prev = cy
    if run_start is not None:
        bands.append((run_start, prev))
    row_h = h / cells
    regions = [
        (0.0, round(start * row_h, 2), round(w, 2), round((end - start + 1) * row_h, 2))
        for start, end in bands
        if (end - start + 1) >= min_rows
    ]
    regions.sort(key=lambda r: r[3], reverse=True)
    return regions


LayoutNodeReport.model_rebuild()

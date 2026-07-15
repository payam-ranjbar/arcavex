"""The service API facade — the one front door above the kernel.

Clients (CLI, MCP, Python) call this facade and never reach into services or built-ins
directly. The facade orchestrates the pipeline (compile -> layout -> render -> export)
using dependencies injected by :mod:`arcavex.bootstrap`, so the kernel imports nothing from
services or built-ins. No raw exception ever leaves this module: unexpected errors are
wrapped as ``ARC-INT-999`` diagnostics.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from arcavex.kernel.contracts.types import (
    ExportOptions,
    MeasureFn,
    RenderOptions,
)
from arcavex.kernel.diagnostics import (
    Diagnostic,
    DiagnosticError,
    diagnostic,
    has_errors,
    internal_error,
)
from arcavex.kernel.ir.models import (
    CompiledDocument,
    CompiledGroup,
    CompiledImage,
    CompiledNode,
    LayoutDocument,
    LayoutNode,
)
from arcavex.kernel.registry import Registries

_EXPORTER_BY_EXT: dict[str, str] = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".pdf": "pdf",
}

# Machine-readable responses carry this so consumers key on a version, not a shape.
RESPONSE_VERSION = 1

# A project/provenance result model — every one carries ``ok`` and ``diagnostics``, so the
# facade's never-raises boundary helper is generic over the concrete report it returns.
_ResultT = TypeVar("_ResultT", bound="BaseModel")


def _output_name(stem: str, fmt: str, locale: str | None) -> str:
    """Build the default output filename ``<stem>.<format>[.<locale>].png`` (§6.3 / DX-3)."""
    locale_seg = f".{locale}" if locale else ""
    return f"{stem}.{fmt}{locale_seg}.png"


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


class RenderResult(BaseModel):
    """The result of a render request."""

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
    """The result of ``arcavex template new``."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    path: str | None = None
    format: str | None = None
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
    """The result of ``arcavex ext add/enable/disable`` — the extension's new state."""

    model_config = ConfigDict(frozen=True)

    response_version: int = RESPONSE_VERSION
    ok: bool
    name: str | None = None
    enabled: bool = False
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
    path ``nodes.<id>[.<field>...]``; ``value`` carries a ``set`` payload and ``node`` the
    mapping an insert introduces. This is the SAME grammar the format/locale/project override
    layers use, applied here to the template file itself so an agent edits a stable node id
    rather than a text span.
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
    """A node's text-overflow outcome, echoed for inspection."""

    model_config = ConfigDict(frozen=True)

    kind: str
    measured_w_pt: float
    measured_h_pt: float
    box_w_pt: float
    box_h_pt: float


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


class SiblingOverlap(BaseModel):
    """Two sibling nodes whose resolved bounds intersect."""

    model_config = ConfigDict(frozen=True)

    a: str
    b: str
    rect_pt: tuple[float, float, float, float]


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


class AuthoringProtocol(Protocol):
    """Template authoring operations injected by bootstrap (scaffold/inspect/split)."""

    def scaffold(self, name: str, target: Path) -> ScaffoldResult:
        """Scaffold a new renderable template directory at ``target``."""
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
        budget: BudgetProtocol | None = None,
        engine_version: str = "",
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
        self._budget = budget
        self._engine_version = engine_version

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
        effective_dpi = dpi or canvas.dpi
        width_px = max(1, round(canvas.width_pt * effective_dpi / 72.0))
        height_px = max(1, round(canvas.height_pt * effective_dpi / 72.0))
        if self._budget is not None:
            # Pre-flight the resource budgets before allocating the surface, located on the
            # template whose canvas/DPI produced it (spec §8.3).
            self._budget.check_surface(width_px, height_px, file=str(template))

        solver = self._registries.layouts.get(self._default_layout)
        layout = solver.solve(compiled.document, self._measure)
        diagnostics.extend(layout.warnings)

        backend = self._registries.backends.get(self._default_backend)
        started = time.monotonic()
        surface = backend.render(layout, RenderOptions(dpi=dpi, debug=debug))
        if self._budget is not None:
            self._budget.check_wall_ms((time.monotonic() - started) * 1000.0, file=str(template))

        exporter = self._registries.exporters.get(exporter_name)
        output.parent.mkdir(parents=True, exist_ok=True)
        opts = ExportOptions(
            quality=quality if quality is not None else 100,
            dpi=dpi,
            lossless=lossless,
            page_width_pt=canvas.width_pt,
            page_height_pt=canvas.height_pt,
            bleed_pt=canvas.bleed_pt,
            engine_version=self._engine_version,
        )
        report = exporter.export(surface, output, opts)

        return RenderResult(
            ok=True,
            output_path=report.path,
            diagnostics=diagnostics,
            content_sha256=report.content_sha256,
            inferred=inferred,
        )

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
                        params=_effect_param_infos(effect.param_schema),
                    )
                )
            return EffectListReport(ok=True, effects=infos)
        except Exception as exc:  # noqa: BLE001 - facade boundary must not leak
            return EffectListReport(
                ok=False, diagnostics=[internal_error("effects list failed", detail=repr(exc))]
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

    def scaffold_template(self, name: str, target: Path) -> ScaffoldResult:
        """Scaffold a new renderable one-file template directory. Never raises."""
        if self._authoring is None:  # pragma: no cover - always wired in production
            return ScaffoldResult(ok=False, diagnostics=[_unwired("authoring")])
        try:
            return self._authoring.scaffold(name, Path(target))
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
    def preview_path(self, template: Path, format_name: str) -> Path:
        """Return the stable preview output path for a template + format.

        The path is derived from the resolved ``template.yaml`` so the same template always
        previews to the same file regardless of whether the caller passed the directory or the
        file (§4.1.1 path equivalence, CR-4), under ``$ARCAVEX_HOME/cache/preview`` or an OS
        temp directory.
        """
        try:
            _root_dir, template_yaml = self._compiler.resolve_paths(template)
            base = template_yaml
        except Exception:  # noqa: BLE001 - fall back to the raw path when resolution fails
            base = Path(template)
        key = hashlib.sha256(str(base.resolve()).encode("utf-8")).hexdigest()[:16]
        root = self._resolve_preview_root()
        return root / f"{key}.{format_name}.png"

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
        out_path = self.preview_path(template, resolved_format)

        render_start = time.perf_counter()
        solver = self._registries.layouts.get(self._default_layout)
        layout = solver.solve(compiled.document, self._measure)
        diagnostics.extend(layout.warnings)
        backend = self._registries.backends.get(self._default_backend)
        surface = backend.render(layout, RenderOptions(dpi=dpi, debug=debug))
        exporter = self._registries.exporters.get("png")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: export to a unique temp file in the same directory, then os.replace so
        # a watcher never observes a torn PNG and a failed render leaves the old file intact.
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
        diagnostics: list[Diagnostic] = []
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
        return PreviewProjectReport(ok=all(p.ok for p in previews), previews=previews)

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
        """Lay out, render, and atomically export a compiled document to ``out_path``.

        Shared by project preview; mirrors the direct-preview atomic write so a failed render
        leaves any prior image intact.
        """
        solver = self._registries.layouts.get(self._default_layout)
        layout = solver.solve(document, self._measure)
        warnings = list(layout.warnings)
        backend = self._registries.backends.get(self._default_backend)
        surface = backend.render(layout, RenderOptions(dpi=dpi, debug=False))
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
        return report, warnings

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


def _effect_param_infos(schema: type[BaseModel]) -> list[EffectParamInfo]:
    """Project a pydantic effect param schema onto reportable field infos (DX-6).

    Type names are author-facing: a length param (points/mm/px) reports ``length`` and a colour
    param reports ``colour``, detected from the field's ``BeforeValidator`` rather than a raw
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


def _build_node_report(
    compiled: CompiledNode,
    layout: LayoutNode,
    group_dir: str,
    dpi: int,
    overlaps: list[SiblingOverlap],
    parent_stack: str | None = None,
) -> LayoutNodeReport:
    b = layout.bounds
    pb = layout.paint_bounds
    scale = dpi / 72.0
    overflow = None
    if layout.overflow.kind != "none" or layout.overflow.measured_h_pt > 0.0:
        overflow = OverflowReport(
            kind=layout.overflow.kind,
            measured_w_pt=layout.overflow.measured_w_pt,
            measured_h_pt=layout.overflow.measured_h_pt,
            box_w_pt=layout.overflow.box_w_pt,
            box_h_pt=layout.overflow.box_h_pt,
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
        _collect_overlaps(layout.children, overlaps, layout.bounds)

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


def _collect_overlaps(
    children: tuple[LayoutNode, ...], overlaps: list[SiblingOverlap], region: object
) -> None:
    visible = [c for c in children if c.visible]
    for i in range(len(visible)):
        for j in range(i + 1, len(visible)):
            a, b = visible[i], visible[j]
            # Rotated nodes contribute their post-transform AABB to overlap reporting (CR-14).
            ra, rb = a.paint_bounds, b.paint_bounds
            rect = _intersection(ra, rb)
            if rect is None:
                continue
            # DX-8/RR2-9: containment is suppressed as noise only when the *container* is a
            # backdrop — a group, or a full-bleed node covering nearly the whole parent region.
            # A regular content node that fully swallows a sibling is a genuine bug and is still
            # reported, rather than hidden just because it happens to enclose the other.
            if _contains(ra, rb) and _is_backdrop(a, region):
                continue
            if _contains(rb, ra) and _is_backdrop(b, region):
                continue
            overlaps.append(
                SiblingOverlap(a=a.source_node_id, b=b.source_node_id, rect_pt=rect)
            )


def _is_backdrop(node: LayoutNode, region: object) -> bool:
    """Whether ``node`` is a backdrop-like container within ``region`` (full-bleed or a group).

    Groups are structural containers, not collisions; a leaf that covers ~the whole parent
    region is a background. Either legitimately encloses siblings, so their containment is not
    reported as an overlap bug.
    """
    if node.kind == "group":
        return True
    rw, rh = region.w, region.h  # type: ignore[attr-defined]
    region_area = rw * rh
    if region_area <= 0:
        return False
    pb = node.paint_bounds
    return bool((pb.w * pb.h) >= 0.9 * region_area)


def _contains(outer: object, inner: object) -> bool:
    """Whether ``outer`` fully contains ``inner`` (small tolerance for quantization)."""
    ox, oy, ow, oh = outer.x, outer.y, outer.w, outer.h  # type: ignore[attr-defined]
    ix, iy, iw, ih = inner.x, inner.y, inner.w, inner.h  # type: ignore[attr-defined]
    eps = 0.01
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
    if x1 - x0 > 0.01 and y1 - y0 > 0.01:
        return (x0, y0, x1 - x0, y1 - y0)
    return None


def _covered_fraction(layout: LayoutDocument, cells: int = 64) -> float:
    """Approximate the fraction of the canvas covered by any leaf node (coarse grid)."""
    w, h = layout.canvas.width_pt, layout.canvas.height_pt
    if w <= 0 or h <= 0:
        return 0.0
    grid = [[False] * cells for _ in range(cells)]

    def mark(node: LayoutNode) -> None:
        if node.children:
            for child in node.children:
                mark(child)
            return
        if not node.visible:
            return
        b = node.bounds
        cx0 = max(0, int(b.x / w * cells))
        cx1 = min(cells, int((b.x + b.w) / w * cells) + 1)
        cy0 = max(0, int(b.y / h * cells))
        cy1 = min(cells, int((b.y + b.h) / h * cells) + 1)
        for cy in range(cy0, cy1):
            for cx in range(cx0, cx1):
                grid[cy][cx] = True

    mark(layout.root)
    covered = sum(row.count(True) for row in grid)
    return round(covered / (cells * cells), 4)


def _free_regions(
    layout: LayoutDocument, cells: int = 64, min_rows: int = 2
) -> list[tuple[float, float, float, float]]:
    """Return maximal full-width empty horizontal bands, largest first (spec §6.1.1).

    Rows of the coarse coverage grid that are entirely uncovered are merged into vertical
    bands; a band is reported when it spans at least ``min_rows`` rows (so trivial slivers are
    dropped). This is the summary that makes an unfilled top/bottom slab obvious.
    """
    w, h = layout.canvas.width_pt, layout.canvas.height_pt
    if w <= 0 or h <= 0:
        return []
    grid = [[False] * cells for _ in range(cells)]

    def mark(node: LayoutNode) -> None:
        if node.children:
            for child in node.children:
                mark(child)
            return
        if not node.visible:
            return
        b = node.bounds
        cx0 = max(0, int(b.x / w * cells))
        cx1 = min(cells, int((b.x + b.w) / w * cells) + 1)
        cy0 = max(0, int(b.y / h * cells))
        cy1 = min(cells, int((b.y + b.h) / h * cells) + 1)
        for cy in range(cy0, cy1):
            for cx in range(cx0, cx1):
                grid[cy][cx] = True

    mark(layout.root)
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

"""Template compiler v0: (template, data, format) -> CompiledDocument.

Loads the one-file template, validates variable declarations against supplied data,
resolves the requested format canvas, evaluates ``{{ … }}`` expressions, expands the
structural constructs ``if``/``repeat`` into compiled sibling nodes, parses constraints and
styles into typed IR, normalizes units to points and colors to RGBA, and validates that node
IDs are unique. Stacks, effects, masks, styles, and locale application are later phases and
are rejected with located "not supported" diagnostics rather than silently ignored.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arcavex.services.style import StylePack, StyleResolver

from pydantic import BaseModel

from arcavex.kernel.api import CompileResult, ResolvedPatch, ResolvedResult
from arcavex.kernel.diagnostics import (
    BUDGET_CODE,
    MISSING_FONT_CODE,
    Diagnostic,
    DiagnosticError,
    diagnostic,
    has_errors,
)
from arcavex.kernel.ir.canonical import canonical_hash
from arcavex.kernel.ir.colors import Color
from arcavex.kernel.ir.models import (
    AnchorEdge,
    CanvasSpec,
    CompiledDocument,
    CompiledGroup,
    CompiledImage,
    CompiledNode,
    CompiledPath,
    CompiledShape,
    CompiledText,
    Constraints,
    EffectSpec,
    FitSpec,
    MaskSpec,
    ParagraphSpec,
    SizeSpec,
    SourceRef,
    StackSpec,
    Style,
    TextRun,
    Transform,
)
from arcavex.kernel.ir.units import Dim
from arcavex.services.template.expressions import (
    BudgetError,
    ExpressionError,
    FunctionTable,
    MissingVariableError,
    UnknownFunctionError,
    render_value,
)
from arcavex.services.template.loader import (
    TemplateSource,
    line_of,
    load_template,
    load_yaml,
    node_line,
)
from arcavex.services.template.overlays import (
    PatchLog,
    apply_patches,
    merge_overlay,
)

_PARENT_EDGES = {"top", "bottom", "left", "right", "center_x", "center_y"}
_LOGICAL_EDGES = {"start", "end"}
# Anchor keys (which edge of *this* node is pinned) and reference edges may both be logical.
_ANCHOR_KEYS = _PARENT_EDGES | _LOGICAL_EDGES
_EDGE_NAMES = _PARENT_EDGES | _LOGICAL_EDGES
_NODE_TYPES = {"group", "text", "image", "shape", "path"}
_STACK_LAYOUTS = {"hstack", "vstack"}
_MAIN_ALIGNS = {"start", "center", "end", "space_between"}
_CROSS_ALIGNS = {"start", "center", "end", "stretch"}
# Image extensions we let skia decode in Phase 0 (checked only for a friendlier error).
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
# Declared variable ``type`` -> the Python types an authored value may take.
_VAR_PY_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "boolean": (bool,),
    "list": (list,),
    "object": (dict,),
    "color": (str,),
    "image": (str,),
}
# Locale setting vocabularies validated for shape in Phase 1 (application is Phase 2, DX-5).
_LOCALE_DIRECTIONS = {"ltr", "rtl"}
_LOCALE_DIGITS = {"en", "fa", "latn", "arab"}
_LOCALE_KEYS = {"direction", "digits", "fonts", "data", "patch"}

# Known field whitelists per sub-block (CR-2). An unknown key here is a located error rather
# than a silently ignored typo, matching how the compiler treats unknown keys elsewhere.
# ``line_height`` is deliberately absent: it is authored-but-unsupported (ARC-TPL-053), so it
# must not appear in the ARC-TPL-051 "valid fields" hint (RR2-12). The dedicated check in
# _parse_style runs before this whitelist so it still gets the specific rejection message.
_STYLE_KEYS = frozenset({
    "fill", "stroke", "stroke_width", "color", "corner_radius", "opacity",
    "font", "font_size", "font_weight", "italic", "align", "direction",
    "letter_spacing",
})
_PARAGRAPH_KEYS = frozenset({"align", "direction"})
_FIT_KEYS = frozenset({"policy", "min_size", "overflow", "max_lines"})
_CONSTRAINT_KEYS = frozenset({"anchor", "size"})
_SIZE_MAP_KEYS = frozenset({"value", "aspect", "min", "max"})
_RUN_KEYS = frozenset({
    "text", "font", "font_size", "font_weight", "italic", "color", "letter_spacing",
})


def _is_within(path: Path, root: Path) -> bool:
    """Return whether ``path`` is ``root`` itself or lives beneath it (both already resolved)."""
    return path == root or root in path.parents


def _style_hash(pack: StylePack | None) -> str | None:
    """Return the canonical hash of a style pack's design tokens, or ``None`` when unstyled.

    Hashes the tokens the compiler actually consumes (name, version, palettes, fonts, presets,
    roles) rather than the file bytes, so equivalent packs authored differently hash the same
    and the digest joins the manifest's recorded inputs (§5.3).
    """
    if pack is None:
        return None
    return canonical_hash(
        {
            "name": pack.name,
            "version": pack.version,
            "palettes": pack.palettes,
            "fonts": pack.fonts,
            "effect_presets": pack.effect_presets,
            "shape_presets": pack.shape_presets,
            "roles": pack.roles,
        }
    )


def _to_plain(obj: Any) -> Any:
    """Convert ruamel structures and scalar subclasses to plain Python values."""
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return float(obj)
    if isinstance(obj, str):
        return str(obj)
    return obj


class Compiler:
    """Compiles a one-file template plus data into a :class:`CompiledDocument`."""

    def __init__(
        self,
        available_fonts: frozenset[str] | None = None,
        functions: FunctionTable | None = None,
        masks: frozenset[str] | None = None,
        mask_schema: Callable[[str], type[BaseModel] | None] | None = None,
        effects: frozenset[str] | None = None,
        effect_schema: Callable[[str], type[BaseModel] | None] | None = None,
        effect_kind: Callable[[str], str | None] | None = None,
        shapes: frozenset[str] | None = None,
        shape_schema: Callable[[str], type[BaseModel] | None] | None = None,
        styles: StyleResolver | None = None,
    ) -> None:
        """Create a compiler.

        Args:
            available_fonts: Font family names present in the bundled font database. When
                supplied, a text node requesting a family outside this set fails compilation
                (and therefore validation) with a located diagnostic. When ``None`` (the
                default used by isolated unit tests) font availability is not enforced.
            functions: The template-function resolution table, wired from the registry by
                :mod:`arcavex.bootstrap`. When ``None`` the evaluator falls back to the
                built-in functions (isolated unit tests).
            masks: Registered mask-component names. When supplied, a node referencing an
                unknown mask fails compilation. ``None`` disables the check (unit tests).
            mask_schema: Resolves a mask name to its pydantic param schema for validation.
            effects: Registered effect names. When supplied, an unknown effect fails
                compilation with a located error listing the registered names.
            effect_schema: Resolves an effect name to its pydantic param schema.
            effect_kind: Resolves an effect name to its category (``geometry``/``color``/
                ``raster``/``composite``), used to reject geometry effects on non-path nodes.
            shapes: Registered shape-generator names.
            shape_schema: Resolves a shape-generator name to its pydantic param schema.
            styles: Style-pack resolver (loads ``style:`` packs). ``None`` disables style
                support (isolated unit tests), leaving a ``style:`` opt-in a located error.
        """
        self._available_fonts = available_fonts
        self._functions = functions
        self._masks = masks
        self._mask_schema = mask_schema
        self._effects = effects
        self._effect_schema = effect_schema
        self._effect_kind = effect_kind
        self._shapes = shapes
        self._shape_schema = shape_schema
        self._styles = styles
        # Per-compile state, (re)initialized at the top of ``compile``.
        self._patch_log: PatchLog = PatchLog()
        self._digits: str | None = None
        self._default_direction: str = "ltr"
        self._font_overrides: dict[str, tuple[str, ...]] = {}
        self._style_pack: StylePack | None = None
        # The authoritative variable snapshot on the rerun path, else ``None`` (§5.3).
        self._resolved_data: dict[str, Any] | None = None

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
        """Compile a template. Returns a document (on success) plus diagnostics.

        ``resolved_data`` is the rerun path: when supplied it is the authoritative variable
        snapshot, so data-file/preview/locale-data resolution is skipped while structural
        resolution (format/locale patches, direction, digits) still runs (§5.3).

        ``project_patch`` is the project override layer (§5.4): a patch list applied to the node
        AST *after* the format and locale patches, so a project's ``overrides/<template>.patch.
        yaml`` is the last structural word. A patch that no longer addresses an existing node
        surfaces the same ``ARC-TPL-092`` a stale format/locale patch would (feeding upgrade's
        stale-path report).
        """
        diags: list[Diagnostic] = []
        inferred: dict[str, str] = {}
        self._patch_log = PatchLog()
        self._digits = None
        self._default_direction = "ltr"
        self._font_overrides = {}
        self._style_pack = None
        self._resolved_data = resolved_data
        try:
            source = load_template(template)
            template_path = source.template_path
            raw = source.raw
            # Canonical template hash captured before any patch mutates the node AST (§3.1.4).
            template_hash = canonical_hash(_to_plain(raw))

            # RR-4: collect every non-goal section offense in one pass instead of raising on
            # the first, so the AI/human correction loop sees them together.
            diags.extend(_collect_unsupported_sections(source))
            diags.extend(self._validate_locales_shape(source))
            if has_errors(diags):
                return CompileResult(None, diags, inferred)

            # Resolve the opted-in style pack first: it is the lowest resolution layer (its
            # palettes feed expressions and its roles/presets feed nodes), sitting under the
            # template's own values (§4.1.4).
            self._style_pack = self._resolve_style(source, style)
            style_hash = _style_hash(self._style_pack)

            # Resolve the requested locale's settings (§4.1.4): direction default, digit policy,
            # font overrides, data overlay, and patch. An undeclared locale is an error.
            loc_settings = self._resolve_locale(source, locale)
            self._digits = loc_settings.get("digits")
            self._default_direction = loc_settings.get("direction", "ltr")
            self._font_overrides = self._font_override_map(loc_settings.get("fonts"))

            canvas, resolved_format = self._resolve_format(source, format_name, inferred)
            seed = _int_field(
                raw.get("seed", 0), template_path, "seed", line_of(raw, "seed")
            )

            root_raw = raw.get("root")
            if not isinstance(root_raw, dict):
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-004",
                        "Template is missing a 'root' node",
                        file=str(template_path),
                        hint="Add a 'root:' group node describing the scene.",
                    )
                )

            # Structural overrides address authored node IDs and run before expressions
            # (§4.1.5): style -> format patch -> locale patch. Applied to the node AST in place.
            self._apply_format_patch(source, resolved_format, root_raw)
            self._apply_locale_patch(source, locale, loc_settings, root_raw)
            if project_patch:
                apply_patches(
                    root_raw, project_patch, "project",
                    project_patch_file or source.template_path, "project.patch",
                    self._patch_log,
                )

            # On the rerun path the snapshot is authoritative, so file/preview/locale data
            # overlays are skipped; template-level patches above still ran for byte-identity.
            if resolved_data is None:
                pre_overlays, post_overlays = self._locale_data_overlays(
                    source, data, locale, loc_settings, inferred
                )
            else:
                pre_overlays, post_overlays = [], []
            context = self._build_context(
                source, data, diags, inferred, pre_overlays, post_overlays
            )
            if has_errors(diags):
                return CompileResult(None, diags, inferred)

            seen_ids: set[str] = set()
            root = self._build_node(
                root_raw, context, template_path, canvas, seen_ids, "root", diags, ""
            )
            if not isinstance(root, CompiledGroup):
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-005",
                        "The root node must be of type 'group'",
                        file=str(template_path),
                        keypath="root.type",
                        line=line_of(root_raw, "type"),
                        hint="Set 'type: group' on the root node.",
                    )
                )

            doc = CompiledDocument(canvas=canvas, seed=seed, root=root)
            # The resolved variable snapshot (defaults/overlays applied) drops derived
            # injections like ``palette`` (re-derived from the style on rerun) so it captures
            # exactly the authored/derived variable values a rerun needs (§5.3).
            snapshot = {k: _to_plain(v) for k, v in context.items() if k != "palette"}
            return CompileResult(
                doc,
                diags,
                inferred,
                format_name=resolved_format,
                resolved_data=snapshot,
                template_hash=template_hash,
                style_hash=style_hash,
                data_hash=canonical_hash(snapshot),
            )
        except DiagnosticError as exc:
            return CompileResult(None, diags + list(exc.diagnostics), inferred)

    def inspect_resolved(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
    ) -> ResolvedResult:
        """Apply the format/locale patch layers and report each value's originating layer (CR-1).

        Runs the same resolution prelude as :meth:`compile` (locale settings, format, then the
        format and locale patches recorded in the :class:`PatchLog`) and reads back the final
        value each ``set``/``insert`` produced from the patched AST. Never raises.
        """
        self._patch_log = PatchLog()
        self._digits = None
        self._default_direction = "ltr"
        self._font_overrides = {}
        self._style_pack = None
        self._resolved_data = None
        diags: list[Diagnostic] = []
        try:
            source = load_template(template)
            diags.extend(_collect_unsupported_sections(source))
            diags.extend(self._validate_locales_shape(source))
            if has_errors(diags):
                return ResolvedResult(ok=False, diagnostics=diags)
            self._style_pack = self._resolve_style(source, None)
            style_ref = (
                f"{self._style_pack.name}@{self._style_pack.version}"
                if self._style_pack is not None
                else None
            )
            loc_settings = self._resolve_locale(source, locale)
            self._digits = loc_settings.get("digits")
            self._default_direction = loc_settings.get("direction", "ltr")
            _canvas, resolved_format = self._resolve_format(source, format_name, {})
            root_raw = source.raw.get("root")
            if not isinstance(root_raw, dict):
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-004",
                        "Template is missing a 'root' node",
                        file=str(source.template_path),
                        hint="Add a 'root:' group node describing the scene.",
                    )
                )
            self._apply_format_patch(source, resolved_format, root_raw)
            self._apply_locale_patch(source, locale, loc_settings, root_raw)
            # The last op touching a path is the one whose value survives; mark it effective.
            last_for_path: dict[str, int] = {}
            for i, rec in enumerate(self._patch_log.records):
                last_for_path[rec.path] = i
            # RR2-10: report the value *each* op set (from the record), not the surviving final
            # value — so an overridden (losing) layer shows what it contributed, not the winner's.
            patches = [
                ResolvedPatch(
                    layer=rec.layer,
                    op=rec.op,
                    path=rec.path,
                    value=_to_plain(rec.value) if rec.op == "set" else None,
                    effective=(last_for_path[rec.path] == i),
                )
                for i, rec in enumerate(self._patch_log.records)
            ]
            return ResolvedResult(
                ok=True,
                format_name=resolved_format,
                locale=locale,
                direction=self._default_direction,
                digits=self._digits,
                style=style_ref,
                patches=patches,
                diagnostics=diags,
            )
        except DiagnosticError as exc:
            return ResolvedResult(ok=False, diagnostics=diags + list(exc.diagnostics))

    def resolve_paths(self, template: Path) -> tuple[Path, Path]:
        """Return ``(root_dir, template_yaml)`` for a template path (file or directory).

        Passing the directory or its ``template.yaml`` resolves to the same pair, so callers
        (default output naming, the preview cache key) treat both spellings identically.
        """
        from arcavex.services.template.loader import resolve_template_path

        return resolve_template_path(Path(template))

    def list_formats(self, template: Path) -> list[str]:
        """Return the sorted names of formats declared by the template (best effort)."""
        try:
            source = load_template(template)
        except DiagnosticError:
            return []
        formats = source.raw.get("formats")
        if not isinstance(formats, dict):
            return []
        return sorted(str(k) for k in formats)

    # ------------------------------------------------------------ variables & context
    def _build_context(
        self,
        source: TemplateSource,
        data: Path | None,
        diags: list[Diagnostic],
        inferred: dict[str, str],
        pre_overlays: list[dict[str, Any]] | None = None,
        post_overlays: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # Rerun path (§5.3): the snapshot is authoritative and already validated, so variable
        # resolution, defaults, and type checks are skipped (re-running them would re-emit
        # coercion warnings). Only the derived ``palette`` injection is reapplied from the
        # resolved style so expressions addressing it evaluate identically.
        if self._resolved_data is not None:
            context = merge_overlay({}, _to_plain(self._resolved_data))
            if self._style_pack is not None and "palette" not in context:
                context["palette"] = {
                    name: list(colors) for name, colors in self._style_pack.palettes.items()
                }
            return context

        raw = source.raw
        var_file = source.file_for("variables")
        variables = raw.get("variables")
        if variables is None:
            variables = {}
        elif not isinstance(variables, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-013",
                    "'variables' must be a mapping of names to declarations",
                    file=str(var_file),
                    keypath="variables",
                    line=node_line(variables),
                    hint="Write 'variables:' as a mapping, e.g. 'title: {type: string}'.",
                )
            )

        # preview_data is a *fallback used only when no --data file is supplied* (§4.1.2 /
        # §6.3). When a data file is given, required/default resolution runs against that
        # data alone; preview values must never backfill a missing supplied variable.
        # ADR-0002 Decision 3 layering (lowest precedence first): preview_data (only when no
        # --data file is supplied) -> template-shipped locales.<L>.data -> user base --data
        # file -> user sidecar data.<L>.yaml overlay. User data always outranks template
        # data; every layer merges over the previous one with the §4.1.4 overlay semantics.
        context: dict[str, Any] = {}
        if data is None:
            preview = _to_plain(raw.get("preview_data") or {})
            if isinstance(preview, dict) and preview:
                context = merge_overlay(context, preview)
                inferred["data"] = "preview_data"
        for overlay in pre_overlays or []:
            context = merge_overlay(context, overlay)
        # CR-8: per-variable line numbers in the data file, captured from the ruamel map
        # before flattening so a value diagnostic can cite '<data.yaml>:<line>'.
        data_lines: dict[str, int | None] = {}
        if data is not None:
            raw_data = load_yaml(data)
            loaded = _to_plain(raw_data)
            if loaded is None:
                loaded = {}
            if not isinstance(loaded, dict):
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-012",
                        "Data file root must be a mapping of variable names to values",
                        file=str(data),
                        hint="Top-level data is 'name: value' pairs, not a list or scalar.",
                    )
                )
            for key in loaded:
                data_lines[str(key)] = line_of(raw_data, str(key))
            context = merge_overlay(context, loaded)

        # User sidecar overlay (data.<locale>.yaml) merges over the base data (§4.1.4).
        for overlay in post_overlays or []:
            context = merge_overlay(context, overlay)
            for key in overlay:
                data_lines.setdefault(str(key), None)

        # CR-10 / ADR-0002: an explicit null in *any* data layer (base data or an overlay) is a
        # value, never omission and never default-resurrection — so keys present with a null
        # value are kept, and only genuine omission (an absent key) falls through to the
        # default/optional-none path below. `provided` records the keys any data layer supplied.
        provided = set(context)

        for name, decl in variables.items():
            decl = decl if isinstance(decl, dict) else {}
            # RR-1: a typo'd / unknown declared type is a located error, not a silent skip of
            # all further checking for this variable.
            declared = decl.get("type")
            if declared is not None and declared not in _VAR_PY_TYPES:
                diags.append(
                    diagnostic(
                        "ARC-TPL-016",
                        f"Variable {name!r} has unknown type {declared!r}",
                        file=str(var_file),
                        keypath=name,
                        line=line_of(variables, name),
                        hint=f"Valid types are: {', '.join(sorted(_VAR_PY_TYPES))}.",
                    )
                )
                continue
            required = bool(decl.get("required", False))
            has_default = "default" in decl
            supplied_null = name in provided and context.get(name) is None
            if supplied_null:
                # Explicit null binds null (a value). A required variable set to null is still
                # an error; an optional one keeps None and skips type/enum checks.
                if required:
                    diags.append(
                        diagnostic(
                            "ARC-TPL-014",
                            f"Variable {name!r} is required but was provided as null",
                            file=str(data) if data is not None else str(var_file),
                            keypath=name,
                            line=data_lines.get(name),
                            hint=(
                                f"Give '{name}:' a non-null value, "
                                "or mark the variable optional in the template."
                            ),
                        )
                    )
                context[name] = None
            elif name not in provided:
                if has_default:
                    default_val = _to_plain(decl["default"])
                    context[name] = self._check_variable_value(
                        name, decl, default_val, data, var_file, variables, diags,
                        data_lines, is_default=True,
                    )
                elif required:
                    # The value is absent from the data file entirely, so there is no data-file
                    # line to cite; report the template's declaration site instead and point
                    # the author at the fix.
                    diags.append(
                        diagnostic(
                            "ARC-TPL-014",
                            f"Variable {name!r} is required but was not provided",
                            file=str(var_file),
                            keypath=name,
                            line=line_of(variables, name),
                            hint=(
                                f"Add '{name}:' to your data file, "
                                "or mark the variable optional in the template."
                                + _overlay_hint(data)
                            ),
                        )
                    )
                else:
                    # A declared optional variable with no default evaluates as none, so
                    # the spec's canonical guard `if: "{{ x is not none }}"` works without
                    # requiring an explicit `default: null` (§4.1.2 example).
                    context[name] = None
            else:
                context[name] = self._check_variable_value(
                    name, decl, context[name], data, var_file, variables, diags,
                    data_lines, is_default=False,
                )
        # Non-declared keys supplied as explicit null stay in context as None (a value), so an
        # expression may reference them; they never resurrect a declared default.
        # Style-pack palettes are exposed under `palette` so expressions can address a colour as
        # `{{ palette.warhol_1[0] }}` (§4.1.3). A template variable named `palette` would shadow
        # this, so only inject when the author has not bound the name themselves.
        if self._style_pack is not None and "palette" not in context:
            context["palette"] = {
                name: list(colors) for name, colors in self._style_pack.palettes.items()
            }
        return context

    def _check_variable_value(
        self,
        name: str,
        decl: dict[str, Any],
        value: Any,
        data: Path | None,
        var_file: Path,
        variables: Any,
        diags: list[Diagnostic],
        data_lines: dict[str, int | None],
        *,
        is_default: bool,
    ) -> Any:
        """Type/enum-check a supplied or default value; return the (possibly coerced) value.

        A default value cites the template declaration; a supplied value cites the data file.
        Per RR-2, a number for a declared ``string`` coerces to text with a warning rather
        than failing; every other mismatch remains a located error.
        """
        # A default always comes from the template declaration line; a supplied value comes
        # from the data file, whose per-key line was captured before flattening (CR-8). A
        # preview_data value has no distinct line, so it falls back to the declaration.
        if is_default:
            src, line = str(var_file), line_of(variables, name)
        elif data is not None:
            src, line = str(data), data_lines.get(name)
        else:
            src, line = str(var_file), line_of(variables, name)

        declared = decl.get("type")
        if isinstance(declared, str) and declared in _VAR_PY_TYPES:
            coerced = self._check_type(name, declared, value, src, line, diags)
            if coerced is not _UNCHANGED:
                value = coerced
        enum = decl.get("enum")
        if isinstance(enum, list) and enum and value not in enum:
            allowed = ", ".join(repr(e) for e in enum)
            diags.append(
                diagnostic(
                    "ARC-TPL-017",
                    f"Variable {name!r} value {value!r} is not one of the allowed values",
                    file=src,
                    keypath=name,
                    line=line,
                    hint=f"Allowed values: {allowed}.",
                )
            )
        return value

    def _check_type(
        self,
        name: str,
        declared: str,
        value: Any,
        src: str,
        line: int | None,
        diags: list[Diagnostic],
    ) -> Any:
        """Return ``_UNCHANGED``, or a coerced value; append a diagnostic on mismatch."""
        # bool is an int subclass, so keep boolean and number distinct in both directions.
        if declared == "boolean":
            ok = isinstance(value, bool)
        elif declared == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, _VAR_PY_TYPES[declared]) and not isinstance(value, bool)
        if ok:
            return _UNCHANGED
        # RR-2: a number supplied for a declared string coerces (locale-aware stringification
        # is the Phase 1 rule anyway) with a warning; other mismatches stay hard errors.
        if declared == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
            coerced = str(int(value)) if isinstance(value, int) else _num_to_str(value)
            diags.append(
                diagnostic(
                    "ARC-TPL-018",
                    f"Variable {name!r} is a number but declared string; using {coerced!r}",
                    severity="warning",
                    file=src,
                    keypath=name,
                    line=line,
                    hint="Quote the value in your data to make the string intent explicit.",
                )
            )
            return coerced
        diags.append(
            diagnostic(
                "ARC-TPL-015",
                f"Variable {name!r} should be {declared} but got {type(value).__name__}",
                file=src,
                keypath=name,
                line=line,
                hint=f"Provide a {declared} value for {name!r}.",
            )
        )
        return _UNCHANGED

    def _validate_locales_shape(self, source: TemplateSource) -> list[Diagnostic]:
        """Validate the shape of a ``locales`` section without applying it (Phase 1).

        Locale application (direction, digit policy, overlays) is Phase 2; here we only accept
        the file so it is not silently dropped, and reject a malformed shape.
        """
        locales = source.raw.get("locales")
        if locales is None:
            return []
        loc_file = source.file_for("locales")
        if not isinstance(locales, dict):
            return [
                diagnostic(
                    "ARC-TPL-098",
                    "'locales' must be a mapping of locale names to locale settings",
                    file=str(loc_file),
                    keypath="locales",
                    line=node_line(locales),
                    hint="Write 'locales:' as e.g. 'fa: {direction: rtl}'.",
                )
            ]
        out: list[Diagnostic] = []
        for loc_name, settings in locales.items():
            if settings is None:
                continue
            if not isinstance(settings, dict):
                out.append(
                    diagnostic(
                        "ARC-TPL-098",
                        f"Locale {loc_name!r} must be a mapping of settings",
                        file=str(loc_file),
                        keypath=f"locales.{loc_name}",
                        line=line_of(locales, str(loc_name)),
                        hint="Each locale is a mapping, e.g. 'fa: {direction: rtl}'.",
                    )
                )
                continue
            out.extend(self._validate_locale_values(loc_name, settings, loc_file))
        return out

    def _validate_locale_values(
        self, loc_name: Any, settings: dict[str, Any], loc_file: Path
    ) -> list[Diagnostic]:
        """Validate one locale entry's field values (DX-5).

        The values are checked now — direction/digit vocabularies and the shape of the
        fonts/data/patch fields — even though locale APPLICATION is Phase 2, so an author
        preparing locale files gets feedback immediately instead of at some future phase.
        """
        base = f"locales.{loc_name}"
        out: list[Diagnostic] = []

        def err(field: str, message: str, hint: str) -> None:
            out.append(
                diagnostic(
                    "ARC-TPL-099",
                    message,
                    file=str(loc_file),
                    keypath=f"{base}.{field}",
                    line=line_of(settings, field),
                    hint=hint,
                )
            )

        for key in settings:
            if key not in _LOCALE_KEYS:
                err(
                    str(key),
                    f"Locale {loc_name!r} has unknown setting {key!r}",
                    f"Known locale settings are: {', '.join(sorted(_LOCALE_KEYS))}.",
                )
        direction = settings.get("direction")
        if direction is not None and direction not in _LOCALE_DIRECTIONS:
            err(
                "direction",
                f"Locale {loc_name!r} has invalid direction {direction!r}",
                f"Use one of: {', '.join(sorted(_LOCALE_DIRECTIONS))}.",
            )
        digits = settings.get("digits")
        if digits is not None and digits not in _LOCALE_DIGITS:
            err(
                "digits",
                f"Locale {loc_name!r} has invalid digits {digits!r}",
                f"Use one of: {', '.join(sorted(_LOCALE_DIGITS))}.",
            )
        if "fonts" in settings and not isinstance(settings["fonts"], dict):
            err(
                "fonts",
                f"Locale {loc_name!r} 'fonts' must be a mapping of role to font stack",
                "Write 'fonts:' as e.g. 'body: [Vazirmatn, Inter]'.",
            )
        if "data" in settings and not isinstance(settings["data"], dict):
            err(
                "data",
                f"Locale {loc_name!r} 'data' overlay must be a mapping",
                "Write 'data:' as a mapping of variable names to overlay values.",
            )
        if "patch" in settings and not isinstance(settings["patch"], list):
            err(
                "patch",
                f"Locale {loc_name!r} 'patch' must be a list of patch operations",
                "Write 'patch:' as a YAML list of set/remove/insert operations.",
            )
        return out

    # -------------------------------------------------------------- locales & patches
    def _resolve_locale(
        self, source: TemplateSource, locale: str | None
    ) -> dict[str, Any]:
        """Return the requested locale's settings, or ``{}`` when no locale is requested.

        A requested locale the template does not declare is an error (Arcavex never silently
        ignores a locale, spec §6.3).
        """
        if locale is None:
            return {}
        locales = source.raw.get("locales")
        loc_file = source.file_for("locales")
        if not isinstance(locales, dict) or locale not in locales:
            available = ", ".join(sorted(locales)) if isinstance(locales, dict) else "(none)"
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-100",
                    f"Template does not declare locale {locale!r}",
                    file=str(loc_file),
                    keypath="locales",
                    line=node_line(locales) if isinstance(locales, dict) else None,
                    hint=f"Declare it under 'locales:', or use one of: {available}.",
                )
            )
        settings = locales.get(locale) or {}
        return _to_plain(settings) if isinstance(settings, dict) else {}

    def _resolve_style(
        self, source: TemplateSource, style_cli: str | None
    ) -> StylePack | None:
        """Resolve the effective style pack from the CLI ``--style`` or the template ``style:``.

        The CLI reference overrides the template's opt-in. A local-file reference from the CLI is
        resolved relative to the working directory the user invoked from (what ``./file.yaml`` on
        a command line means), while a template ``style:`` file reference stays relative to the
        template — so both spellings resolve the path the author expects. When a style is
        requested but this build has no style resolver wired (isolated tests), it is a located
        ``ARC-TPL-090``.
        """
        template_ref = source.raw.get("style")
        from_cli = style_cli is not None
        ref = style_cli if from_cli else template_ref
        base_dir = Path.cwd() if from_cli else source.root_dir
        if ref is None:
            return None
        if not isinstance(ref, str) or not ref:
            raise DiagnosticError(
                diagnostic(
                    "ARC-STY-001",
                    "The 'style' reference must be a 'name@version' or './file.yaml' string",
                    file=str(source.template_path),
                    keypath="style",
                    line=line_of(source.raw, "style"),
                    hint="Write e.g. 'style: pop-art@0.1' or 'style: ./pop-art.yaml'.",
                )
            )
        if self._styles is None:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-090",
                    "Style packs are not available in this build",
                    file=str(source.template_path),
                    keypath="style",
                    hint="Run through the full engine (bootstrap) to use style packs.",
                )
            )
        # Locate a template ``style:`` reference in the source so a missing pack points at the
        # offending line, like the preset/role errors (CR-3/DX-7). A CLI ``--style`` override has
        # no template line, so it resolves without a source location.
        if from_cli:
            return self._styles.resolve(ref, base_dir)
        return self._styles.resolve(
            ref,
            base_dir,
            file=str(source.template_path),
            keypath="style",
            line=line_of(source.raw, "style"),
        )

    @staticmethod
    def _font_override_map(fonts: Any) -> dict[str, tuple[str, ...]]:
        """Build a family/role -> replacement-stack map from a locale ``fonts`` mapping."""
        out: dict[str, tuple[str, ...]] = {}
        if not isinstance(fonts, dict):
            return out
        for key, stack in fonts.items():
            if isinstance(stack, str):
                out[str(key)] = (stack,)
            elif isinstance(stack, list):
                out[str(key)] = tuple(str(f) for f in stack)
        return out

    def _apply_format_patch(
        self, source: TemplateSource, format_name: str, root_raw: dict[str, Any]
    ) -> None:
        formats = source.raw.get("formats")
        if not isinstance(formats, dict):
            return
        spec = formats.get(format_name)
        patch = spec.get("patch") if isinstance(spec, dict) else None
        if isinstance(patch, list) and patch:
            apply_patches(
                root_raw, patch, f"format:{format_name}", source.file_for("formats"),
                f"formats.{format_name}.patch", self._patch_log,
            )

    def _apply_locale_patch(
        self,
        source: TemplateSource,
        locale: str | None,
        loc_settings: dict[str, Any],
        root_raw: dict[str, Any],
    ) -> None:
        patch = loc_settings.get("patch")
        if locale is not None and isinstance(patch, list) and patch:
            apply_patches(
                root_raw, patch, f"locale:{locale}", source.file_for("locales"),
                f"locales.{locale}.patch", self._patch_log,
            )

    def _locale_data_overlays(
        self,
        source: TemplateSource,
        data: Path | None,
        locale: str | None,
        loc_settings: dict[str, Any],
        inferred: dict[str, str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Collect ``(pre, post)`` data overlays for the locale.

        ADR-0002 Decision 3: template-shipped ``locales.<L>.data`` is a *pre* overlay that
        user data merges over (user data always outranks template data); the user's sibling
        ``base.<locale>.yaml`` is a *post* overlay applied over the base data. Both
        applications are reported as inferences.
        """
        pre: list[dict[str, Any]] = []
        post: list[dict[str, Any]] = []
        inline = loc_settings.get("data")
        if isinstance(inline, dict) and inline:
            pre.append(_to_plain(inline))
            if locale is not None:
                inferred["locale_data"] = f"locales.{locale}.data"
        # A sibling data-file variant (base.<locale>.yaml) is applied when it exists, and the
        # inference is reported (§4.1.4 / §6.3).
        if data is not None and locale is not None:
            sibling = data.with_suffix("")
            candidate = sibling.parent / f"{sibling.name}.{locale}{data.suffix}"
            if candidate.is_file():
                loaded = _to_plain(load_yaml(candidate))
                if isinstance(loaded, dict):
                    post.append(loaded)
                    inferred["data_overlay"] = candidate.name
        return pre, post

    # ---------------------------------------------------------------------- formats
    def _resolve_format(
        self,
        source: TemplateSource,
        format_name: str | None,
        inferred: dict[str, str],
    ) -> tuple[CanvasSpec, str]:
        template = source.file_for("formats")
        formats = source.raw.get("formats") or {}
        if not isinstance(formats, dict) or not formats:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-020",
                    "Template declares no formats",
                    file=str(template),
                    hint="Add a 'formats:' section with at least one named canvas.",
                )
            )
        if format_name is None:
            if len(formats) == 1:
                format_name = next(iter(formats))
                inferred["format"] = format_name
            else:
                available = ", ".join(sorted(formats))
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-021",
                        "No format specified and the template defines several",
                        file=str(template),
                        hint=f"Pass --format with one of: {available}",
                    )
                )
        if format_name not in formats:
            available = ", ".join(sorted(formats))
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-022",
                    f"Unknown format {format_name!r}",
                    file=str(template),
                    hint=f"Available formats: {available}",
                )
            )
        spec = formats[format_name] or {}
        canvas_raw = spec.get("canvas") if isinstance(spec, dict) else None
        if not isinstance(canvas_raw, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-023",
                    f"Format {format_name!r} has no canvas",
                    file=str(template),
                    hint="Give the format a 'canvas: {width, height, dpi}'.",
                )
            )
        base = f"formats.{format_name}.canvas"
        dpi = _int_field(
            canvas_raw.get("dpi", 96), template, f"{base}.dpi", line_of(canvas_raw, "dpi")
        )
        if dpi <= 0:
            raise DiagnosticError(
                diagnostic(
                    "ARC-IR-013",
                    f"Canvas dpi must be positive, got {dpi}",
                    file=str(template),
                    keypath=f"{base}.dpi",
                    line=line_of(canvas_raw, "dpi"),
                    hint="Use a positive integer such as 96 or 300.",
                )
            )
        width = _dim(
            canvas_raw.get("width"), template, f"{base}.width", line_of(canvas_raw, "width")
        )
        height = _dim(
            canvas_raw.get("height"), template, f"{base}.height", line_of(canvas_raw, "height")
        )
        bleed_pt = 0.0
        if "bleed" in canvas_raw:
            bleed_pt = _dim(
                canvas_raw.get("bleed"), template, f"{base}.bleed", line_of(canvas_raw, "bleed")
            ).to_pt(dpi)
        return (
            CanvasSpec(
                width_pt=width.to_pt(dpi),
                height_pt=height.to_pt(dpi),
                dpi=dpi,
                bleed_pt=bleed_pt,
            ),
            format_name,
        )

    # ------------------------------------------------------------------------- nodes
    def _build_node(
        self,
        raw: dict[str, Any],
        context: dict[str, Any],
        template: Path,
        canvas: CanvasSpec,
        seen_ids: set[str],
        keypath: str,
        diags: list[Diagnostic],
        id_suffix: str,
        inherited_direction: str | None = None,
    ) -> CompiledNode:
        self._reject_unsupported_constructs(raw, template, keypath)
        if inherited_direction is None:
            inherited_direction = self._default_direction

        authored_id = raw.get("id")
        if not isinstance(authored_id, str) or not authored_id:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-030",
                    "Every node requires a stable 'id'",
                    file=str(template),
                    keypath=f"{keypath}.id",
                    line=node_line(raw),
                    hint="Add a unique human-readable 'id:' to this node.",
                )
            )
        # Inside a repeat expansion every id in the subtree carries the key suffix so IDs stay
        # globally unique and stable (keyed, not index-based): 'card' -> 'card[ann]'.
        node_id = f"{authored_id}{id_suffix}"
        if node_id in seen_ids:
            raise DiagnosticError(
                diagnostic(
                    "ARC-IR-020",
                    f"Duplicate node id {node_id!r}",
                    file=str(template),
                    keypath=f"{keypath}.id",
                    line=line_of(raw, "id"),
                    hint="Node IDs must be unique across the template.",
                )
            )
        seen_ids.add(node_id)

        node_type = raw.get("type")
        if node_type not in _NODE_TYPES:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-031",
                    f"Unknown node type {node_type!r} on node {node_id!r}",
                    file=str(template),
                    keypath=f"{keypath}.type",
                    line=line_of(raw, "type"),
                    hint=f"Use one of: {', '.join(sorted(_NODE_TYPES))}.",
                )
            )

        transform = self._parse_transform(raw, template, node_id, keypath)
        constraints = self._parse_constraints(
            raw, context, canvas, template, node_id, keypath, id_suffix
        )
        style = self._parse_style(raw, context, canvas, template, node_id, keypath)
        visible = bool(raw.get("visible", True))
        z = int(raw.get("z", 0))

        common: dict[str, Any] = {
            "id": node_id,
            "transform": transform,
            "constraints": constraints,
            "style": style,
            "mask": self._parse_mask(raw, template, node_id, keypath),
            "effects": self._parse_effects(
                raw, node_type, context, template, node_id, keypath, canvas.dpi
            ),
            "visible": visible,
            "z": z,
            # Carry the authoring location so layout/render-time diagnostics can locate the
            # node in the source (RR-3). Kept out of the canonical hash (SourceRef.exclude).
            "source": SourceRef(
                file=str(template), keypath=keypath, line=node_line(raw)
            ),
        }

        if node_type == "group":
            children_raw = raw.get("children") or []
            if not isinstance(children_raw, list):
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-032",
                        f"Group {node_id!r} 'children' must be a list",
                        file=str(template),
                        keypath=f"{keypath}.children",
                        hint="Provide 'children:' as a YAML list of nodes.",
                    )
                )
            # A group without an explicit direction inherits the nearest enclosing group's
            # direction (the root default comes from the locale, else ltr) — CR-6/ADR-0002. The
            # direction is resolved before children so it can be threaded into them.
            direction = raw.get("direction", inherited_direction)
            if direction not in {"ltr", "rtl"}:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-033",
                        f"Group {node_id!r} has invalid direction {direction!r}",
                        file=str(template),
                        keypath=f"{keypath}.direction",
                        hint="Use 'ltr' or 'rtl'.",
                    )
                )
            stack_is_stack = raw.get("layout") in _STACK_LAYOUTS
            built: list[CompiledNode] = []
            for i, child in enumerate(children_raw):
                try:
                    built.extend(
                        self._expand_child(
                            child, context, template, canvas, seen_ids, keypath, i, diags,
                            id_suffix, direction, stack_is_stack,
                        )
                    )
                except DiagnosticError as exc:
                    # DX-4: undeclared-variable references are the most common authoring
                    # mistake; collect every one across the whole compile instead of aborting
                    # at the first. Any other error still fails fast so cascades stay contained.
                    if all(d.code == "ARC-TPL-014" for d in exc.diagnostics):
                        diags.extend(exc.diagnostics)
                        continue
                    raise
            children = tuple(built)
            stack = self._parse_stack(raw, canvas, template, node_id, keypath)
            return CompiledGroup(
                **common,
                direction=direction,
                clip=bool(raw.get("clip", False)),
                stack=stack,
                children=children,
            )
        if node_type == "text":
            return self._build_text(common, raw, context, canvas, template, node_id, keypath)
        if node_type == "image":
            asset = raw.get("asset")
            if not isinstance(asset, str) or not asset:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-034",
                        f"Image node {node_id!r} requires an 'asset' path",
                        file=str(template),
                        keypath=f"{keypath}.asset",
                        line=node_line(raw),
                        hint="Set 'asset:' to a template-relative image path.",
                    )
                )
            asset_line = line_of(raw, "asset")
            asset_resolved = self._resolve_text(
                asset, context, template, node_id, keypath, asset_line
            )
            resolved_asset = (template.parent / asset_resolved).resolve()
            # Path/symlink traversal guard (spec §8.3): a *template-relative* asset must stay within
            # the template directory. ``.resolve()`` follows symlinks, so a '..' segment or a link
            # that leads out of the root is caught — a template can never read '../../etc/passwd'.
            # An absolute path is explicit author intent (trusted local authoring), not a relative
            # escape, so it is allowed; only relative paths are containment-checked.
            root = template.parent.resolve()
            if not Path(asset_resolved).is_absolute() and not _is_within(resolved_asset, root):
                raise DiagnosticError(
                    diagnostic(
                        "ARC-AST-004",
                        f"Image asset {asset_resolved!r} escapes the template directory "
                        f"(node {node_id!r})",
                        file=str(template),
                        keypath=f"{keypath}.asset",
                        line=asset_line,
                        hint="Keep assets inside the template directory; a relative '..' path or a "
                        "symlink that points outside it is refused.",
                    )
                )
            # Resolve and check existence at compile time so 'validate' also catches missing
            # assets (§4). The message keeps the author's template-relative path, not the
            # machine-absolute one.
            if not resolved_asset.is_file():
                raise DiagnosticError(
                    diagnostic(
                        "ARC-AST-001",
                        f"Image asset not found: {asset_resolved!r} "
                        f"(node {node_id!r})",
                        file=str(template),
                        keypath=f"{keypath}.asset",
                        line=asset_line,
                        hint="Check the path is relative to the template file and exists.",
                    )
                )
            asset_path = str(resolved_asset)
            fit = raw.get("fit", "cover")
            if fit not in {"fill", "contain", "cover"}:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-035",
                        f"Image node {node_id!r} has invalid fit {fit!r}",
                        file=str(template),
                        keypath=f"{keypath}.fit",
                        hint="Use 'fill', 'contain', or 'cover'.",
                    )
                )
            return CompiledImage(**common, asset_path=asset_path, fit=fit)
        if node_type == "shape":
            generator = raw.get("generator")
            if generator is not None:
                gen, params = self._parse_shape_generator(
                    raw, context, template, node_id, keypath
                )
                return CompiledShape(**common, generator=gen, generator_params=params)
            shape = raw.get("shape", "rect")
            if shape not in {"rect", "rrect", "circle"}:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-036",
                        f"Shape node {node_id!r} has unsupported shape {shape!r}",
                        file=str(template),
                        keypath=f"{keypath}.shape",
                        hint="Use 'rect', 'rrect', 'circle', or a 'generator:' (starburst, "
                        "speech_bubble, qr_code).",
                    )
                )
            return CompiledShape(**common, shape=shape)
        # path
        return CompiledPath(**common, d=str(raw.get("d", "")))

    # --------------------------------------------------------------- structural constructs
    def _expand_child(
        self,
        child: Any,
        context: dict[str, Any],
        template: Path,
        canvas: CanvasSpec,
        seen_ids: set[str],
        parent_keypath: str,
        index: int,
        diags: list[Diagnostic],
        id_suffix: str,
        inherited_direction: str,
        parent_is_stack: bool,
    ) -> list[CompiledNode]:
        """Expand one authored child entry into zero or more compiled sibling nodes.

        A plain node compiles to itself; a ``repeat`` construct expands to one node per item;
        an ``if`` construct includes its node only when the condition is truthy. Expansion is
        compiler-level (spec §4.1.2), so expanded IDs and diagnostics are stable.
        """
        kp = f"{parent_keypath}.children[{index}]"
        if not isinstance(child, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-032",
                    f"Child at {kp} must be a node mapping",
                    file=str(template),
                    keypath=kp,
                    hint="Each child is a node mapping or a 'repeat'/'if' construct.",
                )
            )
        if "repeat" in child and "if" in child:
            # Both on one child is ambiguous and would silently drop one directive — the exact
            # class of behavior the compiler rejects elsewhere (CR-3). Make the author nest them.
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-061",
                    f"Child at {kp} declares both 'repeat' and 'if' on the same node",
                    file=str(template),
                    keypath=kp,
                    line=node_line(child),
                    hint=(
                        "Nest them through a wrapper group: make the repeat's 'node' a group "
                        "whose 'children' list holds the 'if' construct (the condition then "
                        "gates each item), or make the if's 'node' a group whose 'children' "
                        "list holds the 'repeat' construct (the condition gates the whole loop)."
                    ),
                )
            )
        if "repeat" in child:
            return self._expand_repeat(
                child, context, template, canvas, seen_ids, kp, diags, id_suffix,
                inherited_direction, parent_is_stack,
            )
        if "if" in child:
            return self._expand_if(
                child, context, template, canvas, seen_ids, kp, diags, id_suffix,
                inherited_direction,
            )
        return [
            self._build_node(
                child, context, template, canvas, seen_ids, kp, diags, id_suffix,
                inherited_direction,
            )
        ]

    def _expand_if(
        self,
        child: dict[str, Any],
        context: dict[str, Any],
        template: Path,
        canvas: CanvasSpec,
        seen_ids: set[str],
        keypath: str,
        diags: list[Diagnostic],
        id_suffix: str,
        inherited_direction: str,
    ) -> list[CompiledNode]:
        node_raw = self._construct_node(child, template, keypath)
        condition = self._eval_structural(
            child.get("if"), context, template, keypath, "if", line_of(child, "if")
        )
        if _truthy_value(condition):
            return [
                self._build_node(
                    node_raw, context, template, canvas, seen_ids,
                    f"{keypath}.node", diags, id_suffix, inherited_direction,
                )
            ]
        return []

    def _expand_repeat(
        self,
        child: dict[str, Any],
        context: dict[str, Any],
        template: Path,
        canvas: CanvasSpec,
        seen_ids: set[str],
        keypath: str,
        diags: list[Diagnostic],
        id_suffix: str,
        inherited_direction: str,
        parent_is_stack: bool,
    ) -> list[CompiledNode]:
        node_raw = self._construct_node(child, template, keypath)
        as_name = child.get("as")
        if not isinstance(as_name, str) or not as_name:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-054",
                    "A 'repeat' requires an 'as' name for the loop variable",
                    file=str(template),
                    keypath=f"{keypath}.as",
                    line=node_line(child),
                    hint="Add 'as: item' so the node can reference each element.",
                )
            )
        key_raw = child.get("key")
        if not isinstance(key_raw, str) or not key_raw:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-055",
                    "A 'repeat' requires a stable 'key' expression",
                    file=str(template),
                    keypath=f"{keypath}.key",
                    line=node_line(child),
                    hint="Add 'key: \"{{ item.id }}\"' (or '{{ loop.index }}' if order is stable).",
                )
            )
        collection = self._eval_structural(
            child.get("repeat"), context, template, keypath, "repeat", line_of(child, "repeat")
        )
        if not isinstance(collection, list):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-056",
                    f"'repeat' expression must be a list, got {type(collection).__name__}",
                    file=str(template),
                    keypath=f"{keypath}.repeat",
                    line=line_of(child, "repeat"),
                    hint="Iterate over a list variable, e.g. 'repeat: \"{{ guests }}\"'.",
                )
            )
        if len(collection) > _REPEAT_CAP:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-063",
                    f"'repeat' produced {len(collection)} items, over the cap of {_REPEAT_CAP}",
                    file=str(template),
                    keypath=f"{keypath}.repeat",
                    line=line_of(child, "repeat"),
                    hint=f"Reduce the collection to at most {_REPEAT_CAP} items.",
                )
            )
        if "loop.index" in key_raw:
            # Index-derived keys are allowed but flagged: reordering the collection changes
            # every expanded ID (spec §4.1.1).
            diags.append(
                diagnostic(
                    "ARC-TPL-057",
                    "'repeat' key is derived from loop.index; reordering will change node IDs",
                    severity="warning",
                    file=str(template),
                    keypath=f"{keypath}.key",
                    line=line_of(child, "key"),
                    hint="Prefer a stable field like '{{ item.id }}' when the data has one.",
                )
            )
        out: list[CompiledNode] = []
        seen_keys: dict[str, int] = {}
        total = len(collection)
        for i, item in enumerate(collection):
            item_ctx = dict(context)
            item_ctx[as_name] = item
            item_ctx["loop"] = {"index": i, "first": i == 0, "last": i == total - 1}
            key_value = self._eval_structural(
                key_raw, item_ctx, template, keypath, "key", line_of(child, "key")
            )
            key_str = _stringify_key(key_value)
            if key_str in seen_keys:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-058",
                        f"'repeat' produced duplicate key {key_str!r} "
                        f"(items {seen_keys[key_str]} and {i})",
                        file=str(template),
                        keypath=f"{keypath}.key",
                        line=line_of(child, "key"),
                        hint="The key expression must be unique per item for stable IDs.",
                    )
                )
            seen_keys[key_str] = i
            out.append(
                self._build_node(
                    node_raw, item_ctx, template, canvas, seen_ids,
                    f"{keypath}.node", diags, f"{id_suffix}[{key_str}]", inherited_direction,
                )
            )
        # DX-2: a stack positions its own children, so identical-constraint siblings do not
        # overlap there — only warn for repeats in an absolute group.
        if not parent_is_stack:
            self._warn_on_overlap(out, template, keypath, node_line(child), diags)
        return out

    def _warn_on_overlap(
        self,
        nodes: list[CompiledNode],
        template: Path,
        keypath: str,
        line: int | None,
        diags: list[Diagnostic],
    ) -> None:
        """Warn when a repeat expands >1 sibling in an *absolute* group to identical bounds.

        Repeated siblings that share fixed constraints (no per-item offset in their anchors)
        resolve to the same bounds and overlap — an overlap the author cannot see until they
        view the render. This does not fire inside a stack (the stack positions each child) and
        is skipped when the anchors carry per-item ``{{ }}`` expressions that make each item's
        bounds differ, so it flags only the genuine "all on top of each other" case (DX-2).
        """
        if len(nodes) <= 1:
            return
        first = nodes[0]
        if not all(
            n.constraints == first.constraints and n.transform == first.transform
            for n in nodes[1:]
        ):
            return
        diags.append(
            diagnostic(
                "ARC-LAY-040",
                f"'repeat' at {keypath} expands {len(nodes)} sibling nodes with identical "
                "constraints; they resolve to the same bounds and will overlap",
                severity="warning",
                file=str(template),
                keypath=f"{keypath}.node.constraints",
                line=line,
                hint=(
                    "Give each item a distinct anchor (e.g. a per-item offset like "
                    "'top: parent.top+{{ loop.index * 90 }}pt'), or wrap the repeat in a "
                    "'layout: vstack'/'hstack' group so the stack positions each child."
                ),
            )
        )

    def _construct_node(
        self, child: dict[str, Any], template: Path, keypath: str
    ) -> dict[str, Any]:
        node_raw = child.get("node")
        if not isinstance(node_raw, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-059",
                    f"Construct at {keypath} requires a 'node' mapping",
                    file=str(template),
                    keypath=f"{keypath}.node",
                    line=node_line(child),
                    hint="Give the 'repeat'/'if' construct a single 'node:' to expand.",
                )
            )
        return node_raw

    def _eval_structural(
        self,
        raw: Any,
        context: dict[str, Any],
        template: Path,
        keypath: str,
        field: str,
        line: int | None,
    ) -> Any:
        """Evaluate a structural ``repeat``/``if``/``key`` expression to a native value."""
        if not isinstance(raw, str):
            return raw
        try:
            return render_value(raw, context, self._functions)
        except MissingVariableError as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-014",
                    f"'{field}' at {keypath} references undefined variable '{exc.path}'",
                    file=str(template),
                    keypath=f"{keypath}.{field}",
                    line=line,
                    hint=(
                        f"Declare and supply '{exc.path}', or guard it with "
                        f"| default(...).{_did_you_mean(exc.path, context)}"
                    ),
                )
            ) from exc
        except BudgetError as exc:
            raise DiagnosticError(
                diagnostic(
                    BUDGET_CODE,
                    f"'{field}' at {keypath} exceeded its evaluation budget: {exc.message}",
                    file=str(template),
                    keypath=f"{keypath}.{field}",
                    line=line,
                    hint="Simplify the expression.",
                )
            ) from exc
        except ExpressionError as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-060",
                    f"'{field}' at {keypath} has an invalid expression: {exc.message}",
                    file=str(template),
                    keypath=f"{keypath}.{field}",
                    line=line,
                    hint=_expr_hint(exc),
                )
            ) from exc

    # ------------------------------------------------------------------- sub-parsers
    def _reject_unsupported_constructs(
        self, raw: dict[str, Any], template: Path, keypath: str
    ) -> None:
        # All Phase-0 node-level constructs are now supported; effects/masks/shapes are parsed.
        return None

    def _parse_effects(
        self,
        raw: dict[str, Any],
        node_type: str,
        context: dict[str, Any],
        template: Path,
        node_id: str,
        keypath: str,
        dpi: int,
    ) -> tuple[EffectSpec, ...]:
        """Parse a node's ``effect_preset``/``effects`` into validated, ordered effect specs.

        The authoring model is a linear list (spec §4.4). Entries are inline ``{name, params}``
        or ``{preset: X}`` references into the style pack's ``effect_presets``. A shorthand
        ``effect_preset: X`` prepends one preset. Unknown effect names and invalid params are
        located errors; a geometry effect on a non-path node (text/image/group) is rejected.
        """
        entries: list[Any] = []
        preset_key = raw.get("effect_preset")
        if preset_key is not None:
            entries.append({"preset": preset_key})
        raw_effects = raw.get("effects")
        if raw_effects is not None:
            if not isinstance(raw_effects, list):
                raise DiagnosticError(
                    diagnostic(
                        "ARC-FX-903",
                        f"Node {node_id!r} 'effects' must be a list",
                        file=str(template),
                        keypath=f"{keypath}.effects",
                        line=line_of(raw, "effects"),
                        hint="Write 'effects:' as a YAML list of {name, params} entries.",
                    )
                )
            entries.extend(raw_effects)
        if not entries:
            return ()
        if self._effects is None:
            return ()  # isolated unit tests without a registry: effects are not enforced

        specs: list[EffectSpec] = []
        fx_kp = f"{keypath}.effects"
        for entry in entries:
            name, params = self._effect_name_params(entry, template, node_id, fx_kp)
            params = self._eval_params(params, context, template, node_id, fx_kp)
            specs.append(
                self._validate_effect(name, params, node_type, template, node_id, fx_kp, dpi)
            )
        return tuple(specs)

    def _eval_params(
        self,
        params: Any,
        context: dict[str, Any],
        template: Path,
        node_id: str,
        keypath: str,
    ) -> Any:
        """Recursively evaluate ``{{ … }}`` expressions in effect/shape parameter values.

        Component params may vary per node (the pop-art grid drives per-cell effect strengths
        and QR data from expressions, §4.4). String values are resolved with the node context;
        an exact single expression keeps its native type so a numeric param stays numeric.
        """
        if isinstance(params, dict):
            return {
                k: self._eval_params(v, context, template, node_id, keypath)
                for k, v in params.items()
            }
        if isinstance(params, list):
            return [
                self._eval_params(v, context, template, node_id, keypath) for v in params
            ]
        if isinstance(params, str) and "{{" in params:
            try:
                return render_value(params, context, self._functions, self._digits)
            except (ExpressionError, UnknownFunctionError) as exc:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-060",
                        f"Node {node_id!r} parameter expression failed: {exc}",
                        file=str(template), keypath=keypath,
                        hint="Check the expression references declared variables/palette entries.",
                    )
                ) from exc
        return params

    def _effect_name_params(
        self, entry: Any, template: Path, node_id: str, keypath: str
    ) -> tuple[str, dict[str, Any]]:
        if isinstance(entry, str):
            return entry, {}
        if not isinstance(entry, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-903",
                    f"Node {node_id!r} has an effect entry that is not a name or mapping",
                    file=str(template), keypath=keypath, line=node_line(entry),
                    hint="Each effect is a name, '{name, params}', or '{preset: name}'.",
                )
            )
        preset = entry.get("preset")
        if preset is not None:
            if self._style_pack is None:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-STY-010",
                        f"Node {node_id!r} references effect preset {preset!r} but no style is set",
                        file=str(template), keypath=keypath, line=line_of(entry, "preset"),
                        hint="Add 'style:' to the template (or --style) to use effect presets.",
                    )
                )
            spec = self._style_pack.preset(
                str(preset), file=str(template), keypath=keypath, line=line_of(entry, "preset")
            )
            overrides = _to_plain(entry.get("params") or {})
            params = {**_to_plain(spec.get("params") or {}), **overrides}
            return str(spec.get("name", preset)), params
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-903",
                    f"Node {node_id!r} has an effect without a 'name'",
                    file=str(template), keypath=keypath, line=node_line(entry),
                    hint="Give each effect a 'name:' (or a 'preset:' reference).",
                )
            )
        return name, _to_plain(entry.get("params") or {})

    def _validate_effect(
        self,
        name: str,
        params: dict[str, Any],
        node_type: str,
        template: Path,
        node_id: str,
        keypath: str,
        dpi: int,
    ) -> EffectSpec:
        assert self._effects is not None
        if name not in self._effects:
            available = ", ".join(sorted(self._effects)) or "(none)"
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-910",
                    f"Node {node_id!r} references unknown effect {name!r}",
                    file=str(template), keypath=keypath,
                    hint=f"Registered effects: {available}.",
                )
            )
        kind = self._effect_kind(name) if self._effect_kind is not None else None
        if kind == "geometry" and node_type not in {"shape", "path"}:
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-911",
                    f"Geometry effect {name!r} cannot apply to a {node_type!r} node "
                    f"({node_id!r})",
                    file=str(template), keypath=keypath,
                    hint="Geometry effects need a path; use them on 'shape' or 'path' nodes.",
                )
            )
        validated = params
        if self._effect_schema is not None:
            schema = self._effect_schema(name)
            if schema is not None:
                try:
                    # Validate with the canvas DPI in context so a px-valued effect length is
                    # converted to points against the right resolution (DX-4).
                    validated = schema.model_validate(
                        params, context={"dpi": dpi}
                    ).model_dump(mode="json")
                except Exception as exc:  # noqa: BLE001 - pydantic error -> located diagnostic
                    raise DiagnosticError(
                        diagnostic(
                            "ARC-FX-902",
                            f"Node {node_id!r} effect {name!r} has invalid parameters: "
                            f"{_all_errors(exc)}",
                            file=str(template), keypath=keypath,
                            hint="Check each parameter's name, type, and range for this effect.",
                        )
                    ) from exc
        return EffectSpec(name=name, category=kind or "raster", params=validated)

    def _parse_shape_generator(
        self,
        raw: dict[str, Any],
        context: dict[str, Any],
        template: Path,
        node_id: str,
        keypath: str,
    ) -> tuple[str, dict[str, Any]]:
        """Parse and validate a shape ``generator``/``params`` (e.g. starburst, qr_code)."""
        generator = raw.get("generator")
        if not isinstance(generator, str) or not generator:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-036",
                    f"Shape node {node_id!r} 'generator' must be a name",
                    file=str(template), keypath=f"{keypath}.generator",
                    line=line_of(raw, "generator"),
                    hint="Use a registered generator: starburst, speech_bubble, qr_code.",
                )
            )
        if self._shapes is not None and generator not in self._shapes:
            available = ", ".join(sorted(self._shapes)) or "(none)"
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-913",
                    f"Shape node {node_id!r} references unknown generator {generator!r}",
                    file=str(template), keypath=f"{keypath}.generator",
                    line=line_of(raw, "generator"),
                    hint=f"Registered shape generators: {available}.",
                )
            )
        params = _to_plain(raw.get("params") or {})
        if not isinstance(params, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-036",
                    f"Shape node {node_id!r} 'params' must be a mapping",
                    file=str(template), keypath=f"{keypath}.params",
                    line=line_of(raw, "params"),
                    hint="Write 'params: {points: 12, inner_ratio: 0.5}'.",
                )
            )
        params = self._eval_params(
            params, context, template, node_id, f"{keypath}.params"
        )
        if self._shape_schema is not None:
            schema = self._shape_schema(generator)
            if schema is not None:
                try:
                    params = schema(**params).model_dump(mode="json")
                except Exception as exc:  # noqa: BLE001 - pydantic error -> located diagnostic
                    raise DiagnosticError(
                        diagnostic(
                            "ARC-FX-912",
                            f"Shape node {node_id!r} generator {generator!r} has invalid "
                            f"params: {_all_errors(exc)}",
                            file=str(template), keypath=f"{keypath}.params",
                            line=line_of(raw, "params"),
                            hint="Check each parameter's name, type, and range for this generator.",
                        )
                    ) from exc
        return generator, params

    def _parse_mask(
        self, raw: dict[str, Any], template: Path, node_id: str, keypath: str
    ) -> MaskSpec | None:
        """Parse a mask declaration; the mask component's params are validated at render time
        by the registered generator's schema (spec §3.2)."""
        mask = raw.get("mask")
        if mask is None:
            return None
        if not isinstance(mask, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-IR-040",
                    f"Node {node_id!r} 'mask' must be a mapping",
                    file=str(template),
                    keypath=f"{keypath}.mask",
                    line=line_of(raw, "mask"),
                    hint="Write 'mask: {component: diamond_grid, params: {...}}'.",
                )
            )
        component = mask.get("component")
        if not isinstance(component, str) or not component:
            raise DiagnosticError(
                diagnostic(
                    "ARC-IR-040",
                    f"Node {node_id!r} 'mask' needs a 'component' name",
                    file=str(template),
                    keypath=f"{keypath}.mask.component",
                    line=line_of(mask, "component"),
                    hint="Set 'component:' to a registered mask (e.g. rounded_rect, diamond_grid).",
                )
            )
        if self._masks is not None and component not in self._masks:
            available = ", ".join(sorted(self._masks)) or "(none)"
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-901",
                    f"Node {node_id!r} references unknown mask component {component!r}",
                    file=str(template),
                    keypath=f"{keypath}.mask.component",
                    line=line_of(mask, "component"),
                    hint=f"Registered masks: {available}.",
                )
            )
        params = mask.get("params") or {}
        if not isinstance(params, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-IR-040",
                    f"Node {node_id!r} 'mask.params' must be a mapping",
                    file=str(template),
                    keypath=f"{keypath}.mask.params",
                    line=line_of(mask, "params"),
                    hint="Write 'params: {cell: 90pt, gutter: 6pt}'.",
                )
            )
        validated = self._validate_mask_params(
            component, _to_plain(params), template, node_id, keypath, line_of(mask, "params")
        )
        return MaskSpec(component=component, params=validated)

    def _validate_mask_params(
        self,
        component: str,
        params: dict[str, Any],
        template: Path,
        node_id: str,
        keypath: str,
        line: int | None,
    ) -> dict[str, Any]:
        """Validate mask params against the generator's pydantic schema (ARC-FX-902)."""
        if self._mask_schema is None:
            return params
        schema = self._mask_schema(component)
        if schema is None:
            return params
        try:
            model = schema(**params)
        except Exception as exc:  # noqa: BLE001 - pydantic ValidationError -> located diagnostic
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-902",
                    f"Node {node_id!r} mask {component!r} has invalid params: {_all_errors(exc)}",
                    file=str(template),
                    keypath=f"{keypath}.mask.params",
                    line=line,
                    hint="Check each parameter's name, type, and range for this mask.",
                )
            ) from exc
        return model.model_dump(mode="json")

    # --------------------------------------------------------------------- stacks
    def _parse_stack(
        self, raw: dict[str, Any], canvas: CanvasSpec, template: Path, node_id: str, keypath: str
    ) -> StackSpec:
        layout = raw.get("layout", "absolute")
        if layout in (None, "absolute"):
            return StackSpec()
        if layout not in _STACK_LAYOUTS:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-039",
                    f"Group {node_id!r} has invalid layout {layout!r}",
                    file=str(template),
                    keypath=f"{keypath}.layout",
                    line=line_of(raw, "layout"),
                    hint="Use 'absolute', 'hstack', or 'vstack'.",
                )
            )
        dpi = canvas.dpi
        gap = 0.0
        if "gap" in raw:
            gap = _dim(raw.get("gap"), template, f"{keypath}.gap", line_of(raw, "gap")).to_pt(dpi)
        pt, pr, pb, pl = self._parse_padding(raw.get("padding"), dpi, template, node_id, keypath)
        main_align = raw.get("main_align", "start")
        if main_align not in _MAIN_ALIGNS:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-039",
                    f"Group {node_id!r} has invalid main_align {main_align!r}",
                    file=str(template),
                    keypath=f"{keypath}.main_align",
                    line=line_of(raw, "main_align"),
                    hint=f"Use one of: {', '.join(sorted(_MAIN_ALIGNS))}.",
                )
            )
        cross_align = raw.get("cross_align", "start")
        if cross_align not in _CROSS_ALIGNS:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-039",
                    f"Group {node_id!r} has invalid cross_align {cross_align!r}",
                    file=str(template),
                    keypath=f"{keypath}.cross_align",
                    line=line_of(raw, "cross_align"),
                    hint=f"Use one of: {', '.join(sorted(_CROSS_ALIGNS))}.",
                )
            )
        if bool(raw.get("wrap", False)):
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-056",
                    f"Group {node_id!r} sets 'wrap: true', which is not supported in this build",
                    file=str(template),
                    keypath=f"{keypath}.wrap",
                    line=line_of(raw, "wrap"),
                    hint="Wrapping stacks are deferred; lay out wrapped rows explicitly for now.",
                )
            )
        return StackSpec(
            kind=layout,
            gap_pt=gap,
            pad_top_pt=pt,
            pad_right_pt=pr,
            pad_bottom_pt=pb,
            pad_left_pt=pl,
            main_align=main_align,
            cross_align=cross_align,
        )

    def _parse_padding(
        self, value: Any, dpi: int, template: Path, node_id: str, keypath: str
    ) -> tuple[float, float, float, float]:
        if value is None:
            return 0.0, 0.0, 0.0, 0.0
        kp = f"{keypath}.padding"
        if isinstance(value, dict):
            return (
                _dim(value.get("top", 0), template, f"{kp}.top").to_pt(dpi),
                _dim(value.get("right", 0), template, f"{kp}.right").to_pt(dpi),
                _dim(value.get("bottom", 0), template, f"{kp}.bottom").to_pt(dpi),
                _dim(value.get("left", 0), template, f"{kp}.left").to_pt(dpi),
            )
        if isinstance(value, list) and len(value) == 4:
            sides = [_dim(v, template, f"{kp}[{i}]").to_pt(dpi) for i, v in enumerate(value)]
            return sides[0], sides[1], sides[2], sides[3]
        p = _dim(value, template, kp).to_pt(dpi)
        return p, p, p, p

    # ----------------------------------------------------------------------- text
    def _build_text(
        self,
        common: dict[str, Any],
        raw: dict[str, Any],
        context: dict[str, Any],
        canvas: CanvasSpec,
        template: Path,
        node_id: str,
        keypath: str,
    ) -> CompiledText:
        style: Style = common["style"]
        runs_raw = raw.get("runs")
        if runs_raw is not None:
            if not isinstance(runs_raw, list):
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-040",
                        f"Text node {node_id!r} 'runs' must be a list",
                        file=str(template),
                        keypath=f"{keypath}.runs",
                        line=line_of(raw, "runs"),
                        hint="Write 'runs:' as a list of strings or {text, ...} mappings.",
                    )
                )
            runs: list[TextRun] = []
            parts: list[str] = []
            for i, run_raw in enumerate(runs_raw):
                run = self._parse_run(
                    run_raw, context, style, canvas, template, node_id, f"{keypath}.runs[{i}]"
                )
                runs.append(run)
                parts.append(run.text)
            text = "".join(parts)
            runs_tuple = tuple(runs)
        else:
            text = self._resolve_text(
                raw.get("text", ""), context, template, node_id, keypath, line_of(raw, "text"),
                localize=True,
            )
            runs_tuple = (TextRun(text=text),)
        paragraph = self._parse_paragraph(raw, style, template, node_id, keypath)
        fit = self._parse_fit(raw, canvas, template, node_id, keypath)
        return CompiledText(
            **common, text=text, runs=runs_tuple, paragraph=paragraph, fit=fit
        )

    def _parse_run(
        self,
        run_raw: Any,
        context: dict[str, Any],
        style: Style,
        canvas: CanvasSpec,
        template: Path,
        node_id: str,
        keypath: str,
    ) -> TextRun:
        if isinstance(run_raw, str):
            return TextRun(
                text=self._resolve_text(
                    run_raw, context, template, node_id, keypath, None, localize=True
                )
            )
        if not isinstance(run_raw, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-040",
                    f"Text node {node_id!r} run at {keypath} must be a string or mapping",
                    file=str(template),
                    keypath=keypath,
                    hint="Each run is a string or a {text, font, font_size, ...} mapping.",
                )
            )
        self._reject_unknown_keys(run_raw, _RUN_KEYS, "run", template, node_id, keypath)
        text = self._resolve_text(
            run_raw.get("text", ""), context, template, node_id, keypath,
            line_of(run_raw, "text"), localize=True,
        )
        font = run_raw.get("font")
        if isinstance(font, str):
            families: tuple[str, ...] = (font,)
        elif isinstance(font, list):
            families = tuple(str(f) for f in font)
        else:
            families = ()
        families = self._override_fonts(families)
        self._check_fonts(families, template, node_id, keypath, line_of(run_raw, "font"))
        font_size = run_raw.get("font_size")
        size_pt = (
            _dim(font_size, template, f"{keypath}.font_size", line_of(run_raw, "font_size")).to_pt(
                canvas.dpi
            )
            if font_size is not None
            else None
        )
        color = self._color(
            run_raw.get("color"), context, template, node_id, keypath, "color",
            line_of(run_raw, "color"),
        )
        weight = run_raw.get("font_weight")
        letter_spacing = run_raw.get("letter_spacing")
        return TextRun(
            text=text,
            font_families=families,
            font_size_pt=size_pt,
            font_weight=int(weight) if weight is not None else None,
            italic=bool(run_raw["italic"]) if "italic" in run_raw else None,
            color=color,
            letter_spacing_pt=(
                _dim(letter_spacing, template, f"{keypath}.letter_spacing").to_pt(canvas.dpi)
                if letter_spacing is not None
                else None
            ),
        )

    def _parse_paragraph(
        self, raw: dict[str, Any], style: Style, template: Path, node_id: str, keypath: str
    ) -> ParagraphSpec:
        p = raw.get("paragraph") or {}
        if not isinstance(p, dict):
            p = {}
        self._reject_unknown_keys(
            p, _PARAGRAPH_KEYS, "paragraph", template, node_id, f"{keypath}.paragraph"
        )
        align = p.get("align", style.align)
        if align not in {"left", "right", "center", "start", "end"}:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-037",
                    f"Node {node_id!r} has invalid paragraph align {align!r}",
                    file=str(template),
                    keypath=f"{keypath}.paragraph.align",
                    line=line_of(p, "align"),
                    hint="Use left, right, center, start, or end.",
                )
            )
        direction = p.get("direction")
        if direction is None:
            style_raw = raw.get("style")
            style_dir = style_raw.get("direction") if isinstance(style_raw, dict) else None
            direction = style_dir if style_dir in {"ltr", "rtl"} else "auto"
        if direction not in {"ltr", "rtl", "auto"}:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-038",
                    f"Node {node_id!r} has invalid paragraph direction {direction!r}",
                    file=str(template),
                    keypath=f"{keypath}.paragraph.direction",
                    line=line_of(p, "direction"),
                    hint="Use 'ltr', 'rtl', or 'auto'.",
                )
            )
        return ParagraphSpec(align=align, direction=direction)

    def _parse_fit(
        self, raw: dict[str, Any], canvas: CanvasSpec, template: Path, node_id: str, keypath: str
    ) -> FitSpec:
        f = raw.get("fit")
        if f is None:
            return FitSpec()
        if not isinstance(f, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-041",
                    f"Text node {node_id!r} 'fit' must be a mapping",
                    file=str(template),
                    keypath=f"{keypath}.fit",
                    line=line_of(raw, "fit"),
                    hint="Write 'fit: {policy: shrink_to_fit, min_size: 24pt}'.",
                )
            )
        self._reject_unknown_keys(f, _FIT_KEYS, "fit", template, node_id, f"{keypath}.fit")
        policy = f.get("policy", "wrap")
        if policy not in {"wrap", "shrink_to_fit", "truncate"}:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-041",
                    f"Text node {node_id!r} has invalid fit policy {policy!r}",
                    file=str(template),
                    keypath=f"{keypath}.fit.policy",
                    line=line_of(f, "policy"),
                    hint="Use 'wrap', 'shrink_to_fit', or 'truncate'.",
                )
            )
        overflow = f.get("overflow", "clip")
        if overflow not in {"clip", "allow", "error"}:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-041",
                    f"Text node {node_id!r} has invalid overflow {overflow!r}",
                    file=str(template),
                    keypath=f"{keypath}.fit.overflow",
                    line=line_of(f, "overflow"),
                    hint="Use 'clip', 'allow', or 'error'.",
                )
            )
        min_size = f.get("min_size")
        min_pt = (
            _dim(min_size, template, f"{keypath}.fit.min_size", line_of(f, "min_size")).to_pt(
                canvas.dpi
            )
            if min_size is not None
            else None
        )
        max_lines = f.get("max_lines")
        max_lines_int = (
            _int_field(max_lines, template, f"{keypath}.fit.max_lines", line_of(f, "max_lines"))
            if max_lines is not None
            else None
        )
        return FitSpec(
            policy=policy, min_size_pt=min_pt, overflow=overflow, max_lines=max_lines_int
        )

    def _parse_transform(
        self, raw: dict[str, Any], template: Path, node_id: str, keypath: str
    ) -> Transform:
        t = raw.get("transform")
        if not isinstance(t, dict):
            return Transform()
        t_line = line_of(raw, "transform")
        rotate = _float_field(t.get("rotate", 0.0), template, f"{keypath}.transform.rotate", t_line)
        scale = t.get("scale", 1.0)
        if isinstance(scale, bool):
            scale_pair = (1.0, 1.0)  # handled by the malformed branch below
        elif isinstance(scale, (int, float)):
            scale_pair = (float(scale), float(scale))
        elif isinstance(scale, list) and len(scale) == 2:
            scale_pair = (
                _float_field(scale[0], template, f"{keypath}.transform.scale[0]", t_line),
                _float_field(scale[1], template, f"{keypath}.transform.scale[1]", t_line),
            )
        else:
            scale_pair = (1.0, 1.0)
        if scale_pair != (1.0, 1.0):
            # Rotation is supported (Phase 2); scaling still is not.
            raise DiagnosticError(
                diagnostic(
                    "ARC-RND-901",
                    f"Scale transforms are not supported yet on {node_id!r}",
                    file=str(template),
                    keypath=f"{keypath}.transform.scale",
                    line=line_of(raw, "transform"),
                    hint="Only translation and rotation are supported.",
                )
            )
        origin = self._parse_origin(t, template, keypath, t_line)
        translate = t.get("translate", [0.0, 0.0])
        if isinstance(translate, list) and len(translate) == 2:
            tr = (
                _float_field(translate[0], template, f"{keypath}.transform.translate[0]", t_line),
                _float_field(translate[1], template, f"{keypath}.transform.translate[1]", t_line),
            )
        else:
            tr = (0.0, 0.0)
        return Transform(translate=tr, rotate_deg=rotate, origin=origin)

    def _parse_origin(
        self, t: dict[str, Any], template: Path, keypath: str, line: int | None
    ) -> tuple[float, float] | None:
        """Parse a transform origin as a relative (0..1, 0..1) pair; default (centre) is None."""
        origin = t.get("origin")
        if origin is None:
            return None
        if isinstance(origin, list) and len(origin) == 2:
            return (
                _float_field(origin[0], template, f"{keypath}.transform.origin[0]", line),
                _float_field(origin[1], template, f"{keypath}.transform.origin[1]", line),
            )
        named = {
            "center": (0.5, 0.5),
            "top_left": (0.0, 0.0),
            "top_right": (1.0, 0.0),
            "bottom_left": (0.0, 1.0),
            "bottom_right": (1.0, 1.0),
        }
        if isinstance(origin, str) and origin in named:
            return named[origin]
        raise DiagnosticError(
            diagnostic(
                "ARC-IR-014",
                f"Invalid transform origin {origin!r} at {keypath}.transform.origin",
                file=str(template),
                keypath=f"{keypath}.transform.origin",
                line=line,
                hint="Use [x, y] in 0..1, or a name like 'center' or 'top_left'.",
            )
        )

    def _parse_constraints(
        self,
        raw: dict[str, Any],
        context: dict[str, Any],
        canvas: CanvasSpec,
        template: Path,
        node_id: str,
        keypath: str,
        id_suffix: str,
    ) -> Constraints:
        c = raw.get("constraints")
        if not isinstance(c, dict):
            # No constraints at all: fill the parent, anchored top-left. This is the
            # convenience default for the root group, full-bleed backgrounds, and stack
            # children (whose position comes from the stack).
            return Constraints(
                anchors={
                    "top": AnchorEdge(edge="top"),
                    "left": AnchorEdge(edge="left"),
                },
                width=SizeSpec(mode="fill"),
                height=SizeSpec(mode="fill"),
            )
        self._reject_unknown_keys(
            c, _CONSTRAINT_KEYS, "constraints", template, node_id, f"{keypath}.constraints"
        )
        anchors = self._parse_anchors(
            c.get("anchor") or {}, context, canvas.dpi, template, node_id, keypath, id_suffix
        )
        # A present-but-incomplete constraints block is under-constrained, not silently
        # filled: each axis needs an explicit size (spec §4.2).
        size = c.get("size")
        size_line = line_of(c, "size")
        if not isinstance(size, dict):
            raise DiagnosticError(
                diagnostic(
                    "ARC-LAY-032",
                    f"Node {node_id!r} has 'constraints' but no 'size'",
                    file=str(template),
                    keypath=f"{keypath}.constraints.size",
                    line=size_line,
                    hint="Add 'size: {w: ..., h: ...}' (each of fixed/%/fill/fit_content/aspect).",
                )
            )
        width = self._parse_size_axis(
            size.get("w"), context, canvas.dpi, template, node_id, keypath, "w", size_line,
            required=True,
        )
        height = self._parse_size_axis(
            size.get("h"), context, canvas.dpi, template, node_id, keypath, "h", size_line,
            required=True,
        )
        return Constraints(anchors=anchors, width=width, height=height)

    def _parse_anchors(
        self,
        anchor_raw: dict[str, Any],
        context: dict[str, Any],
        dpi: int,
        template: Path,
        node_id: str,
        keypath: str,
        id_suffix: str,
    ) -> dict[str, AnchorEdge]:
        anchors: dict[str, AnchorEdge] = {}
        for key, value in anchor_raw.items():
            key_line = line_of(anchor_raw, key)
            if key not in _ANCHOR_KEYS:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LAY-010",
                        f"Node {node_id!r} has unknown anchor {key!r}",
                        file=str(template),
                        keypath=f"{keypath}.constraints.anchor.{key}",
                        line=key_line,
                        hint=f"Anchor keys are: {', '.join(sorted(_ANCHOR_KEYS))}.",
                    )
                )
            resolved = self._resolve_text(
                str(value), context, template, node_id,
                f"{keypath}.constraints.anchor.{key}", key_line,
            )
            anchors[key] = _parse_anchor_value(
                resolved, dpi, template, node_id, keypath, key, key_line, id_suffix
            )
        return anchors

    def _parse_size_axis(
        self,
        value: Any,
        context: dict[str, Any],
        dpi: int,
        template: Path,
        node_id: str,
        keypath: str,
        axis: str,
        line: int | None,
        *,
        required: bool,
    ) -> SizeSpec:
        """Parse one axis size: a scalar (fixed/%/fill/fit_content) or a mapping with aspect/
        min/max. Expressions inside scalar strings are evaluated first (§12.5)."""
        if value is None:
            if required:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LAY-032",
                        f"Node {node_id!r} is under-constrained: no {axis!r} size given",
                        file=str(template),
                        keypath=f"{keypath}.constraints.size.{axis}",
                        line=line,
                        hint="Give this axis fixed (e.g. 100px), a %, 'fill', 'fit_content', "
                        "or {aspect: 'W:H'}.",
                    )
                )
            return SizeSpec(mode="fill")
        min_pt: float | None = None
        max_pt: float | None = None
        if isinstance(value, dict):
            self._reject_unknown_keys(
                value, _SIZE_MAP_KEYS, f"size {axis!r}", template, node_id,
                f"{keypath}.constraints.size.{axis}",
            )
            if "min" in value:
                min_pt = _dim(
                    value.get("min"), template, f"{keypath}.constraints.size.{axis}.min", line
                ).to_pt(dpi)
            if "max" in value:
                max_pt = _dim(
                    value.get("max"), template, f"{keypath}.constraints.size.{axis}.max", line
                ).to_pt(dpi)
            if "aspect" in value:
                aw, ah = _parse_aspect(
                    value.get("aspect"), template, node_id, keypath, axis, line
                )
                return SizeSpec(
                    mode="aspect", aspect_w=aw, aspect_h=ah, min_pt=min_pt, max_pt=max_pt
                )
            base = value.get("value")
            if base is None:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-IR-012",
                        f"Node {node_id!r} size {axis!r} mapping needs 'value' or 'aspect'",
                        file=str(template),
                        keypath=f"{keypath}.constraints.size.{axis}",
                        line=line,
                        hint="Write {value: 62%, min: 100px} or {aspect: '3:4'}.",
                    )
                )
            resolved = self._resolve_text(
                str(base), context, template, node_id, f"{keypath}.constraints.size.{axis}", line
            )
            spec = _parse_size(resolved, dpi, template, node_id, keypath, axis, line)
            return spec.model_copy(update={"min_pt": min_pt, "max_pt": max_pt})
        resolved = self._resolve_text(
            str(value), context, template, node_id, f"{keypath}.constraints.size.{axis}", line
        )
        return _parse_size(resolved, dpi, template, node_id, keypath, axis, line)

    def _reject_unknown_keys(
        self,
        mapping: dict[str, Any],
        allowed: frozenset[str],
        block: str,
        template: Path,
        node_id: str,
        keypath: str,
    ) -> None:
        """Reject any key not in ``allowed`` with a located error listing the valid fields (CR-2).

        This turns a misspelled field (``font_wieght``, ``kerning``) into an authoring error at
        validation time rather than a silently ignored no-op.
        """
        for key in mapping:
            if str(key) not in allowed:
                valid = ", ".join(sorted(allowed))
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-051",
                        f"Node {node_id!r} has unknown {block} field {str(key)!r}",
                        file=str(template),
                        keypath=f"{keypath}.{key}",
                        line=line_of(mapping, str(key)),
                        hint=f"Valid {block} fields are: {valid}.",
                    )
                )

    def _parse_style(
        self,
        raw: dict[str, Any],
        context: dict[str, Any],
        canvas: CanvasSpec,
        template: Path,
        node_id: str,
        keypath: str,
    ) -> Style:
        s = raw.get("style")
        # A style_role pulls default fields from the style pack; the node's own style overrides
        # them (style defaults -> template values, §4.1.4).
        role_defaults = self._role_style(raw, template, node_id, keypath)
        if role_defaults:
            merged = dict(role_defaults)
            if isinstance(s, dict):
                merged.update(s)
            s = merged
        if not isinstance(s, dict):
            return Style()
        dpi = canvas.dpi
        style_kp = f"{keypath}.style"
        # ``line_height`` is authored-but-unsupported: reject it with its specific message
        # *before* the generic whitelist so the two diagnostics stay consistent (RR2-12).
        if "line_height" in s:
            # Accepted end-to-end but unsupported by the skia-python 144 text stack (its
            # StrutStyle exposes no height override), so reject it rather than silently drop
            # it (§4.3: unsupported typography fields fail validation).
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-053",
                    f"Node {node_id!r} sets 'line_height', which is not supported in this build",
                    file=str(template),
                    keypath=f"{style_kp}.line_height",
                    line=line_of(s, "line_height"),
                    hint="Line-height control arrives when the text stack gains strut support.",
                )
            )
        self._reject_unknown_keys(s, _STYLE_KEYS, "style", template, node_id, style_kp)
        fill = self._color(
            s.get("fill"), context, template, node_id, keypath, "fill", line_of(s, "fill")
        )
        stroke = self._color(
            s.get("stroke"), context, template, node_id, keypath, "stroke", line_of(s, "stroke")
        )
        text_color = self._color(
            s.get("color"), context, template, node_id, keypath, "color", line_of(s, "color")
        )
        font = s.get("font")
        if isinstance(font, str):
            families: tuple[str, ...] = (font,)
        elif isinstance(font, list):
            families = tuple(str(f) for f in font)
        else:
            families = ()
        families = self._override_fonts(families)
        self._check_fonts(families, template, node_id, style_kp, line_of(s, "font"))
        font_size = s.get("font_size")
        font_size_pt = (
            _dim(font_size, template, f"{style_kp}.font_size", line_of(s, "font_size")).to_pt(dpi)
            if font_size is not None
            else None
        )
        align = s.get("align", "start")
        if align not in {"left", "right", "center", "start", "end"}:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-037",
                    f"Node {node_id!r} has invalid text align {align!r}",
                    file=str(template),
                    keypath=f"{keypath}.style.align",
                    hint="Use left, right, center, start, or end.",
                )
            )
        direction = s.get("direction", "ltr")
        if direction not in {"ltr", "rtl"}:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-038",
                    f"Node {node_id!r} has invalid text direction {direction!r}",
                    file=str(template),
                    keypath=f"{keypath}.style.direction",
                    hint="Use 'ltr' or 'rtl'.",
                )
            )
        stroke_width = s.get("stroke_width")
        corner_radius = s.get("corner_radius")
        letter_spacing = s.get("letter_spacing")
        return Style(
            fill=fill,
            stroke=stroke,
            stroke_width_pt=(
                _dim(stroke_width, template, f"{style_kp}.stroke_width", line_of(s, "stroke_width"))
                .to_pt(dpi)
                if stroke_width is not None
                else 0.0
            ),
            corner_radius_pt=(
                _dim(
                    corner_radius,
                    template,
                    f"{style_kp}.corner_radius",
                    line_of(s, "corner_radius"),
                ).to_pt(dpi)
                if corner_radius is not None
                else 0.0
            ),
            opacity=_float_field(
                s.get("opacity", 1.0), template, f"{style_kp}.opacity", line_of(s, "opacity")
            ),
            font_families=families,
            font_size_pt=font_size_pt,
            font_weight=_int_field(
                s.get("font_weight", 400), template, f"{style_kp}.font_weight",
                line_of(s, "font_weight"),
            ),
            italic=bool(s.get("italic", False)),
            text_color=text_color,
            align=align,
            direction=direction,
            line_height=None,
            letter_spacing_pt=(
                _dim(
                    letter_spacing, template, f"{style_kp}.letter_spacing",
                    line_of(s, "letter_spacing"),
                ).to_pt(dpi)
                if letter_spacing is not None
                else 0.0
            ),
        )

    def _role_style(
        self, raw: dict[str, Any], template: Path, node_id: str, keypath: str
    ) -> dict[str, Any]:
        """Return the style defaults for a node's ``style_role`` from the active style pack.

        A role's ``font`` may name a font stack declared under the pack's ``fonts:`` (e.g.
        ``font: display``), which is resolved to that family list. Referencing a role without a
        style, or an undefined role, is a located error.
        """
        role_name = raw.get("style_role")
        if role_name is None:
            return {}
        line = line_of(raw, "style_role")
        if self._style_pack is None:
            raise DiagnosticError(
                diagnostic(
                    "ARC-STY-011",
                    f"Node {node_id!r} sets style_role {role_name!r} but no style is set",
                    file=str(template), keypath=f"{keypath}.style_role", line=line,
                    hint="Add 'style:' to the template (or --style) to use style roles.",
                )
            )
        defaults = dict(
            self._style_pack.role(
                str(role_name), file=str(template),
                keypath=f"{keypath}.style_role", line=line,
            )
        )
        font_ref = defaults.get("font")
        if isinstance(font_ref, str) and font_ref in self._style_pack.fonts:
            defaults["font"] = list(self._style_pack.fonts[font_ref])
        return defaults

    def _override_fonts(self, families: tuple[str, ...]) -> tuple[str, ...]:
        """Substitute any family the active locale overrides (spec §4.1.4 font overrides).

        A locale ``fonts: {Inter: [Vazirmatn, Inter]}`` swaps requested Inter for a
        Persian-capable stack while leaving other families untouched.
        """
        if not self._font_overrides:
            return families
        out: list[str] = []
        for family in families:
            out.extend(self._font_overrides.get(family, (family,)))
        return tuple(out)

    def _check_fonts(
        self,
        families: tuple[str, ...],
        template: Path,
        node_id: str,
        style_kp: str,
        line: int | None,
    ) -> None:
        """Fail compilation if a requested font family is not in the bundled font DB.

        Font resolution is a render-stack concern, so the diagnostic lives in the
        ``ARC-RND`` namespace; the CLI maps it to exit 3 (missing font, §6.1.3). Skipped
        when the compiler was built without a font database (isolated unit tests).
        """
        if self._available_fonts is None or not families:
            return
        for family in families:
            if family not in self._available_fonts:
                available = ", ".join(sorted(self._available_fonts)) or "(none)"
                raise DiagnosticError(
                    diagnostic(
                        MISSING_FONT_CODE,
                        f"Node {node_id!r} requests font family {family!r}, "
                        "which is not in the bundled font database",
                        file=str(template),
                        keypath=f"{style_kp}.font",
                        line=line,
                        hint=f"Available families: {available}.",
                    )
                )

    def _color(
        self,
        value: Any,
        context: dict[str, Any],
        template: Path,
        node_id: str,
        keypath: str,
        field: str,
        line: int | None = None,
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        resolved = self._resolve_text(str(value), context, template, node_id, keypath, line)
        try:
            return Color.parse(resolved).as_tuple()
        except ValueError as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-IR-030",
                    f"Node {node_id!r} has invalid color in '{field}': {resolved!r}",
                    file=str(template),
                    keypath=f"{keypath}.style.{field}",
                    line=line,
                    hint="Use #hex, rgb()/rgba(), or a named color.",
                )
            ) from exc

    def _resolve_text(
        self,
        raw: Any,
        context: dict[str, Any],
        template: Path,
        node_id: str,
        keypath: str,
        line: int | None = None,
        *,
        localize: bool = False,
    ) -> str:
        # The locale digit policy applies only to *displayed* text (localize=True), never to
        # constraint/color/asset strings — mapping '40pt' to Persian digits would break parsing.
        if not isinstance(raw, str):
            return str(raw)
        try:
            digits = self._digits if localize else None
            value = render_value(raw, context, self._functions, digits)
        except MissingVariableError as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-014",
                    f"Node {node_id!r} references undefined variable '{exc.path}'",
                    file=str(template),
                    keypath=keypath,
                    line=line,
                    hint=(
                        f"Declare '{exc.path}' in variables and supply it, or use "
                        f"| default(...).{_did_you_mean(exc.path, context)}"
                    ),
                )
            ) from exc
        except BudgetError as exc:
            # BudgetError subclasses ExpressionError, so it must be caught first. Budget
            # exhaustion is a resource limit (exit 4), not a syntax error (exit 1).
            raise DiagnosticError(
                diagnostic(
                    BUDGET_CODE,
                    f"Node {node_id!r} expression exceeded its evaluation budget: {exc.message}",
                    file=str(template),
                    keypath=keypath,
                    line=line,
                    hint="Simplify the expression; it hit the evaluation/token budget.",
                )
            ) from exc
        except ExpressionError as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-060",
                    f"Node {node_id!r} has an invalid expression: {exc.message}",
                    file=str(template),
                    keypath=keypath,
                    line=line,
                    hint=_expr_hint(exc),
                )
            ) from exc
        if isinstance(value, str):
            return value
        from arcavex.services.template.expressions import localize_digits, stringify

        text = stringify(value)
        # CR-8: an exact-match numeric expression ("{{ n }}") bypasses render_value's
        # per-fragment digit mapping, so apply the active digit policy here too. This makes
        # "{{ n }}" and "n = {{ n }}" agree under --locale fa.
        if localize and self._digits and isinstance(value, (int, float)) and not isinstance(
            value, bool
        ):
            text = localize_digits(text, self._digits)
        return text


# ------------------------------------------------------------------- module helpers
# Iteration cap for structural 'repeat' (spec §4.1.2). Exceeding it is a resource error.
_REPEAT_CAP = 1000

# Sentinel returned by type checking to mean "value unchanged" (distinct from None, which is
# a legitimate coerced value the caller may want to keep).
_UNCHANGED = object()

# Template-level sections still deferred to later phases. Authoring one is a located error,
# not a silent no-op. Per RR-4 these are collected together rather than raised on the first.
# Defining style packs *inline* in a template is still unsupported — packs are external files a
# template opts into with a scalar ``style:`` reference (handled during compile, not rejected).
_UNSUPPORTED_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("styles", "ARC-TPL-093", "Define palettes/presets in a style pack file and reference it."),
)


def _reject_unsupported(code: str, what: str, template: Path, detail: str) -> CompileResult:
    return CompileResult(
        None,
        [
            diagnostic(
                code,
                f"{what.capitalize()} are not supported in this build",
                file=str(template),
                hint=f"{detail}.",
            )
        ],
    )


def _collect_unsupported_sections(source: TemplateSource) -> list[Diagnostic]:
    """Return one diagnostic per still-unsupported section, aggregated (RR-4).

    Covers deferred template-level sections (styles/style), a ``styles.yaml`` sidecar (Phase
    3), and per-format ``patch`` operations (Phase 2) — all reported together so the
    correction loop sees every offense in one run.
    """
    raw = source.raw
    out: list[Diagnostic] = []
    for key, code, detail in _UNSUPPORTED_SECTIONS:
        if key in raw:
            out.append(
                diagnostic(
                    code,
                    f"Template-level '{key}' section is not supported in this build",
                    file=str(source.template_path),
                    keypath=key,
                    line=line_of(raw, key),
                    hint=detail,
                )
            )
    styles_sidecar = source.root_dir / "styles.yaml"
    if styles_sidecar.is_file():
        out.append(
            diagnostic(
                "ARC-TPL-096",
                "Split-template sidecar 'styles.yaml' is not supported in this build",
                file=str(styles_sidecar),
                hint="Style packs arrive in Phase 3.",
            )
        )
    return out


def _overlay_hint(data: Path | None) -> str:
    """Return a hint suffix when the --data file looks like a locale overlay sidecar (DX-10).

    A ``data.fa.yaml``-style name (a ``<base>.<locale>.<ext>`` sidecar) is a *partial* overlay
    meant to ride on the base data file, so passing it directly to ``--data`` surfaces missing
    base variables; the hint redirects the author to the base file plus ``--locale``.
    """
    if data is None:
        return ""
    suffixes = Path(data).suffixes  # e.g. ['.fa', '.yaml']
    if len(suffixes) >= 2:
        locale_tok = suffixes[-2].lstrip(".")
        if 2 <= len(locale_tok) <= 8 and locale_tok.isalpha():
            base = Path(data).name[: -len("".join(suffixes[-2:]))] + suffixes[-1]
            return (
                f" This file looks like a locale overlay ('{Path(data).name}'); pass the base "
                f"data file ('{base}') with '--locale {locale_tok}' instead."
            )
    return ""


def _did_you_mean(name: str, context: dict[str, Any]) -> str:
    """Return a ' Did you mean 'x'?' suffix for the nearest declared variable (DX-10).

    Only bare (undotted) names are suggested — the common ``{{ titel }}`` typo — matched
    against the variables currently in scope. Returns an empty string when nothing is close.
    """
    import difflib

    if "." in name:
        return ""
    candidates = [k for k in context if isinstance(k, str) and k != "loop"]
    matches = difflib.get_close_matches(name, candidates, n=1)
    return f" Did you mean {matches[0]!r}?" if matches else ""


def _expr_hint(exc: ExpressionError) -> str | None:
    """Return the ARC-TPL-060 hint, dropping the generic one when the message is precise.

    An unknown-function error already lists the available functions, so a generic "check the
    syntax" hint is noise (DX-10); a genuine parse error still benefits from it.
    """
    if isinstance(exc, UnknownFunctionError):
        return None
    return "Check the '{{ … }}' expression syntax and each function's expected arguments."


def _num_to_str(value: float) -> str:
    """Render a float value the way string interpolation does."""
    return str(int(value)) if float(value).is_integer() else repr(value)


def _truthy_value(value: Any) -> bool:
    """Truthiness for structural ``if`` (booleans/null/numbers/strings/collections)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return bool(value)


def _stringify_key(value: Any) -> str:
    """Render a repeat key value to the string used inside expanded node IDs."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _num_to_str(value)
    return str(value)


def _int_field(value: Any, template: Path, keypath: str, line: int | None) -> int:
    """Coerce an authored value to ``int`` or raise a located ARC-IR diagnostic."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _coercion_error(value, template, keypath, line, "an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _coercion_error(value, template, keypath, line, "an integer") from exc


def _float_field(value: Any, template: Path, keypath: str, line: int | None) -> float:
    """Coerce an authored value to ``float`` or raise a located ARC-IR diagnostic."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _coercion_error(value, template, keypath, line, "a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise _coercion_error(value, template, keypath, line, "a number") from exc


def _coercion_error(
    value: Any, template: Path, keypath: str, line: int | None, want: str
) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-IR-014",
            f"Value {value!r} at {keypath} is not {want}",
            file=str(template),
            keypath=keypath,
            line=line,
            hint=f"Provide {want}.",
        )
    )


def _dim(value: Any, template: Path, keypath: str, line: int | None = None) -> Dim:
    if value is None:
        raise DiagnosticError(
            diagnostic(
                "ARC-IR-010",
                f"Missing dimension at {keypath}",
                file=str(template),
                keypath=keypath,
                line=line,
                hint="Provide a value such as '40pt', '210mm', or '1080px'.",
            )
        )
    try:
        return Dim.parse(value)
    except ValueError as exc:
        raise DiagnosticError(
            diagnostic(
                "ARC-IR-011",
                f"Invalid dimension {value!r} at {keypath}",
                file=str(template),
                keypath=keypath,
                line=line,
                hint="Use a number with an optional unit: px, pt, mm, or %.",
            )
        ) from exc


def _parse_aspect(
    value: Any, template: Path, node_id: str, keypath: str, axis: str, line: int | None
) -> tuple[float, float]:
    """Parse an aspect ratio ``'W:H'`` (or ``[W, H]``) into ``(this_axis, other_axis)``."""
    pair: tuple[Any, Any] | None = None
    if isinstance(value, str) and ":" in value:
        left, _, right = value.partition(":")
        pair = (left.strip(), right.strip())
    elif isinstance(value, list) and len(value) == 2:
        pair = (value[0], value[1])
    if pair is None:
        raise DiagnosticError(
            diagnostic(
                "ARC-IR-012",
                f"Node {node_id!r} has invalid aspect {value!r} on axis {axis!r}",
                file=str(template),
                keypath=f"{keypath}.constraints.size.{axis}.aspect",
                line=line,
                hint="Write aspect as 'W:H', e.g. '3:4'.",
            )
        )
    try:
        w, h = float(pair[0]), float(pair[1])
    except (TypeError, ValueError) as exc:
        raise DiagnosticError(
            diagnostic(
                "ARC-IR-012",
                f"Node {node_id!r} has non-numeric aspect {value!r} on axis {axis!r}",
                file=str(template),
                keypath=f"{keypath}.constraints.size.{axis}.aspect",
                line=line,
                hint="Both parts of an aspect ratio must be numbers, e.g. '16:9'.",
            )
        ) from exc
    if w <= 0 or h <= 0:
        raise DiagnosticError(
            diagnostic(
                "ARC-IR-012",
                f"Node {node_id!r} aspect {value!r} must be positive on both parts",
                file=str(template),
                keypath=f"{keypath}.constraints.size.{axis}.aspect",
                line=line,
                hint="Use positive numbers, e.g. '3:4'.",
            )
        )
    # The axis carrying 'aspect' is this-axis; the ratio maps this:other, so for the h axis
    # 'aspect: 3:4' means h = w * 4/3 — flip so aspect_w/aspect_h is always this/other.
    return (w, h) if axis == "w" else (h, w)


def _first_error(exc: Exception) -> str:
    """Return a short message from a pydantic ValidationError (or any exception)."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            items = errors()
        except Exception:  # noqa: BLE001
            items = []
        if items:
            first = items[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            return f"{loc}: {first.get('msg', 'invalid')}" if loc else str(first.get("msg"))
    return str(exc)


def _all_errors(exc: Exception) -> str:
    """Return every offending field from a pydantic ValidationError, joined (DX-5).

    Pydantic already collects each field error in one pass, so reporting them all lets an author
    fix every mistake at once instead of one render-and-fail round trip per field. Falls back to
    a single message for non-validation exceptions.
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            items = errors()
        except Exception:  # noqa: BLE001
            items = []
        parts: list[str] = []
        for item in items:
            loc = ".".join(str(p) for p in item.get("loc", ()))
            msg = str(item.get("msg", "invalid"))
            parts.append(f"{loc}: {msg}" if loc else msg)
        if parts:
            return "; ".join(parts)
    return str(exc)


def _parse_size(
    value: Any, dpi: int, template: Path, node_id: str, keypath: str, axis: str,
    line: int | None = None,
) -> SizeSpec:
    if value is None:
        return SizeSpec(mode="fill")
    if isinstance(value, str):
        low = value.strip().lower()
        if low == "fill":
            return SizeSpec(mode="fill")
        if low in {"fit_content", "fit-content"}:
            return SizeSpec(mode="fit_content")
        # `aspect(W:H)` string sugar — the spec §4.2 literal form — is equivalent to the
        # canonical mapping `{aspect: 'W:H'}`; both are accepted (DX-5).
        if low.startswith("aspect(") and low.endswith(")"):
            aw, ah = _parse_aspect(
                value.strip()[len("aspect("):-1], template, node_id, keypath, axis, line
            )
            return SizeSpec(mode="aspect", aspect_w=aw, aspect_h=ah)
        if low.endswith("%"):
            try:
                return SizeSpec(mode="percent", percent=float(low[:-1]))
            except ValueError as exc:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-IR-012",
                        f"Invalid percent size {value!r} on {node_id!r}",
                        file=str(template),
                        keypath=f"{keypath}.constraints.size.{axis}",
                        line=line,
                        hint="Use a value like '62%'.",
                    )
                ) from exc
    dim = _dim(value, template, f"{keypath}.constraints.size.{axis}", line)
    return SizeSpec(mode="fixed", value_pt=dim.to_pt(dpi))


def _parse_anchor_value(
    value: str, dpi: int, template: Path, node_id: str, keypath: str, key: str,
    line: int | None, id_suffix: str,
) -> AnchorEdge:
    """Parse ``<ref>.<edge>[±offset]`` where ``ref`` is ``parent`` or a sibling id.

    ``{{ }}`` expressions in the value are already evaluated by the caller. Logical ``start``/
    ``end`` edges are kept as-is and resolved by the layout solver via the group direction.
    Sibling refs are suffixed with the current repeat key so they resolve to the expanded id.
    """
    text = value.strip()
    dot = text.find(".")
    if dot <= 0:
        raise DiagnosticError(
            diagnostic(
                "ARC-LAY-011",
                f"Node {node_id!r} anchor {key!r} must reference an edge like 'parent.top'",
                file=str(template),
                keypath=f"{keypath}.constraints.anchor.{key}",
                line=line,
                hint="Write anchors like 'parent.top', 'parent.left+20pt', or 'title.bottom+8pt'.",
            )
        )
    ref = text[:dot]
    rest = text[dot + 1 :]
    offset_pt = 0.0
    edge = rest
    for sign_char in ("+", "-"):
        idx = rest.find(sign_char)
        if idx > 0:
            edge = rest[:idx].strip()
            offset_raw = "".join(rest[idx:].split())
            try:
                offset_pt = Dim.parse(offset_raw).to_pt(dpi)
            except ValueError as exc:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LAY-012",
                        f"Node {node_id!r} anchor {key!r} has invalid offset {offset_raw!r}",
                        file=str(template),
                        keypath=f"{keypath}.constraints.anchor.{key}",
                        line=line,
                        hint=(
                            "An unevaluated '{{ }}' expression cannot appear here (expressions "
                            "are resolved before offset parsing). Offsets look like '+20px', "
                            "'+20pt', or '-6mm'."
                            if "{{" in offset_raw
                            else "Offsets look like '+20px', '+20pt', or '-6mm'."
                        ),
                    )
                ) from exc
            break
    edge = edge.strip()
    if edge not in _EDGE_NAMES:
        raise DiagnosticError(
            diagnostic(
                "ARC-LAY-013",
                f"Node {node_id!r} anchor {key!r} references unknown edge {edge!r}",
                file=str(template),
                keypath=f"{keypath}.constraints.anchor.{key}",
                line=line,
                hint=f"Edges are: {', '.join(sorted(_EDGE_NAMES))}.",
            )
        )
    # A sibling ref inside a repeat expansion carries the same key suffix so it resolves to the
    # expanded sibling id (e.g. 'title' -> 'title[ann]'); 'parent' is never suffixed.
    resolved_ref = "parent" if ref == "parent" else f"{ref}{id_suffix}"
    return AnchorEdge(ref=resolved_ref, edge=edge, offset_pt=offset_pt)  # type: ignore[arg-type]

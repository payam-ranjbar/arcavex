"""Template compiler v0: (template, data, format) -> CompiledDocument.

Loads the one-file template, validates variable declarations against supplied data,
resolves the requested format canvas, evaluates ``{{ … }}`` expressions, parses constraints
and styles into typed IR, normalizes units to points and colors to RGBA, and validates that
node IDs are unique. Structural constructs (``if``/``repeat``), stacks, effects, masks,
styles, and locales are Phase 1+ and are rejected with located "not supported" diagnostics
rather than silently ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arcavex.kernel.api import CompileResult
from arcavex.kernel.diagnostics import (
    BUDGET_CODE,
    MISSING_FONT_CODE,
    Diagnostic,
    DiagnosticError,
    diagnostic,
    has_errors,
)
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
    SizeSpec,
    SourceRef,
    Style,
    Transform,
)
from arcavex.kernel.ir.units import Dim
from arcavex.services.template.expressions import (
    BudgetError,
    ExpressionError,
    FunctionTable,
    MissingVariableError,
    render_value,
)
from arcavex.services.template.loader import (
    TemplateSource,
    line_of,
    load_template,
    load_yaml,
    node_line,
)

_PARENT_EDGES = {"top", "bottom", "left", "right", "center_x", "center_y"}
_NODE_TYPES = {"group", "text", "image", "shape", "path"}
_STACK_TYPES = {"hstack", "vstack"}
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
        """
        self._available_fonts = available_fonts
        self._functions = functions

    def compile(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
    ) -> CompileResult:
        """Compile a template. Returns a document (on success) plus diagnostics."""
        diags: list[Diagnostic] = []
        inferred: dict[str, str] = {}
        try:
            if style is not None:
                return _reject_unsupported(
                    "ARC-TPL-090", "style packs", Path(template), "styles are Phase 3"
                )
            if locale is not None:
                # Locale files are parsed for shape in Phase 1, but applying a requested
                # locale (direction/digit policy/overlays) is Phase 2.
                return _reject_unsupported(
                    "ARC-TPL-091", "locales", Path(template), "locale application is Phase 2"
                )

            source = load_template(template)
            template_path = source.template_path
            raw = source.raw

            # RR-4: collect every non-goal section offense in one pass instead of raising on
            # the first, so the AI/human correction loop sees them together.
            diags.extend(_collect_unsupported_sections(source))
            diags.extend(self._validate_locales_shape(source))
            if has_errors(diags):
                return CompileResult(None, diags, inferred)

            context = self._build_context(source, data, diags, inferred)
            if has_errors(diags):
                return CompileResult(None, diags, inferred)

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
            return CompileResult(doc, diags, inferred, format_name=resolved_format)
        except DiagnosticError as exc:
            return CompileResult(None, diags + list(exc.diagnostics), inferred)

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
    ) -> dict[str, Any]:
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
        context: dict[str, Any] = {}
        if data is not None:
            loaded = _to_plain(load_yaml(data))
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
            context.update(loaded)
        else:
            preview = _to_plain(raw.get("preview_data") or {})
            if isinstance(preview, dict) and preview:
                context.update(preview)
                inferred["data"] = "preview_data"

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
            if name not in context:
                if has_default:
                    default_val = _to_plain(decl["default"])
                    context[name] = self._check_variable_value(
                        name, decl, default_val, data, var_file, variables, diags, is_default=True
                    )
                elif required:
                    # Report the template's declaration site: a real (file, line) pair. The
                    # value is missing from the data file, so the data file has no line to
                    # cite; the hint points the author at the fix.
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
                    name, decl, context[name], data, var_file, variables, diags, is_default=False
                )
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
        *,
        is_default: bool,
    ) -> Any:
        """Type/enum-check a supplied or default value; return the (possibly coerced) value.

        A default value cites the template declaration; a supplied value cites the data file.
        Per RR-2, a number for a declared ``string`` coerces to text with a warning rather
        than failing; every other mismatch remains a located error.
        """
        # A default always comes from the template declaration line; a supplied value comes
        # from the data file (which has no per-variable line to cite).
        if is_default:
            src, line = str(var_file), line_of(variables, name)
        else:
            src, line = (str(data), None) if data is not None else (str(var_file), None)

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
            if settings is not None and not isinstance(settings, dict):
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
        return out

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
    ) -> CompiledNode:
        self._reject_unsupported_constructs(raw, template, keypath)

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
        if node_type in _STACK_TYPES:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-052",
                    f"Stack node type {node_type!r} is not supported in this build",
                    file=str(template),
                    keypath=f"{keypath}.type",
                    line=line_of(raw, "type"),
                    hint="Stacks arrive in Phase 2; use anchor constraints for now.",
                )
            )
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
        constraints = self._parse_constraints(raw, canvas, template, node_id, keypath)
        style = self._parse_style(raw, context, canvas, template, node_id, keypath)
        visible = bool(raw.get("visible", True))
        z = int(raw.get("z", 0))

        common: dict[str, Any] = {
            "id": node_id,
            "transform": transform,
            "constraints": constraints,
            "style": style,
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
            built: list[CompiledNode] = []
            for i, child in enumerate(children_raw):
                built.extend(
                    self._expand_child(
                        child, context, template, canvas, seen_ids, keypath, i, diags, id_suffix
                    )
                )
            children = tuple(built)
            direction = raw.get("direction", "ltr")
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
            return CompiledGroup(
                **common,
                direction=direction,
                clip=bool(raw.get("clip", False)),
                children=children,
            )
        if node_type == "text":
            text = self._resolve_text(
                raw.get("text", ""), context, template, node_id, keypath, line_of(raw, "text")
            )
            return CompiledText(**common, text=text)
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
            shape = raw.get("shape", "rect")
            if shape not in {"rect", "rrect", "circle"}:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-TPL-036",
                        f"Shape node {node_id!r} has unsupported shape {shape!r}",
                        file=str(template),
                        keypath=f"{keypath}.shape",
                        hint="Phase 0 shapes are 'rect', 'rrect', or 'circle'.",
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
        if "repeat" in child:
            return self._expand_repeat(
                child, context, template, canvas, seen_ids, kp, diags, id_suffix
            )
        if "if" in child:
            return self._expand_if(
                child, context, template, canvas, seen_ids, kp, diags, id_suffix
            )
        return [
            self._build_node(child, context, template, canvas, seen_ids, kp, diags, id_suffix)
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
    ) -> list[CompiledNode]:
        node_raw = self._construct_node(child, template, keypath)
        condition = self._eval_structural(
            child.get("if"), context, template, keypath, "if", line_of(child, "if")
        )
        if _truthy_value(condition):
            return [
                self._build_node(
                    node_raw, context, template, canvas, seen_ids,
                    f"{keypath}.node", diags, id_suffix,
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
                    f"{keypath}.node", diags, f"{id_suffix}[{key_str}]",
                )
            )
        return out

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
                    hint=f"Declare and supply '{exc.path}', or guard it with | default(...).",
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
                    hint="Check the '{{ … }}' expression syntax.",
                )
            ) from exc

    # ------------------------------------------------------------------- sub-parsers
    def _reject_unsupported_constructs(
        self, raw: dict[str, Any], template: Path, keypath: str
    ) -> None:
        layout = raw.get("layout")
        if layout in {"hstack", "vstack"}:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-052",
                    f"Stack layout {layout!r} is not supported in this build",
                    file=str(template),
                    keypath=f"{keypath}.layout",
                    line=line_of(raw, "layout"),
                    hint="Stacks arrive in Phase 2; use anchor constraints for now.",
                )
            )
        if raw.get("effects"):
            raise DiagnosticError(
                diagnostic(
                    "ARC-FX-900",
                    "Effects are not supported in this build",
                    file=str(template),
                    keypath=f"{keypath}.effects",
                    line=line_of(raw, "effects"),
                    hint="Effects arrive in Phase 3.",
                )
            )
        if raw.get("mask"):
            raise DiagnosticError(
                diagnostic(
                    "ARC-RND-900",
                    "Masks are not supported in this build",
                    file=str(template),
                    keypath=f"{keypath}.mask",
                    line=line_of(raw, "mask"),
                    hint="Masks arrive in Phase 2.",
                )
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
        if rotate != 0.0 or scale_pair != (1.0, 1.0):
            raise DiagnosticError(
                diagnostic(
                    "ARC-RND-901",
                    f"Rotation/scale transforms are not supported yet on {node_id!r}",
                    file=str(template),
                    keypath=f"{keypath}.transform",
                    line=line_of(raw, "transform"),
                    hint="Only translation is supported in Phase 0.",
                )
            )
        translate = t.get("translate", [0.0, 0.0])
        if isinstance(translate, list) and len(translate) == 2:
            tr = (
                _float_field(translate[0], template, f"{keypath}.transform.translate[0]", t_line),
                _float_field(translate[1], template, f"{keypath}.transform.translate[1]", t_line),
            )
        else:
            tr = (0.0, 0.0)
        return Transform(translate=tr)

    def _parse_constraints(
        self,
        raw: dict[str, Any],
        canvas: CanvasSpec,
        template: Path,
        node_id: str,
        keypath: str,
    ) -> Constraints:
        c = raw.get("constraints")
        if not isinstance(c, dict):
            # No constraints at all: fill the parent, anchored top-left. This is the
            # convenience default for the root group and full-bleed backgrounds.
            return Constraints(
                anchors={
                    "top": AnchorEdge(edge="top"),
                    "left": AnchorEdge(edge="left"),
                },
                width=SizeSpec(mode="fill"),
                height=SizeSpec(mode="fill"),
            )
        anchors = self._parse_anchors(c.get("anchor") or {}, canvas.dpi, template, node_id, keypath)
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
                    hint="Add 'size: {w: ..., h: ...}' (each of fixed/%/fill/fit_content).",
                )
            )
        width = _parse_size_required(
            size.get("w"), canvas.dpi, template, node_id, keypath, "w", size_line
        )
        height = _parse_size_required(
            size.get("h"), canvas.dpi, template, node_id, keypath, "h", size_line
        )
        return Constraints(anchors=anchors, width=width, height=height)

    def _parse_anchors(
        self,
        anchor_raw: dict[str, Any],
        dpi: int,
        template: Path,
        node_id: str,
        keypath: str,
    ) -> dict[str, AnchorEdge]:
        anchors: dict[str, AnchorEdge] = {}
        for key, value in anchor_raw.items():
            key_line = line_of(anchor_raw, key)
            if key not in _PARENT_EDGES:
                raise DiagnosticError(
                    diagnostic(
                        "ARC-LAY-010",
                        f"Node {node_id!r} has unknown anchor {key!r}",
                        file=str(template),
                        keypath=f"{keypath}.constraints.anchor.{key}",
                        line=key_line,
                        hint=f"Anchor keys are: {', '.join(sorted(_PARENT_EDGES))}.",
                    )
                )
            anchors[key] = _parse_anchor_value(
                str(value), dpi, template, node_id, keypath, key, key_line
            )
        return anchors

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
        if not isinstance(s, dict):
            return Style()
        dpi = canvas.dpi
        style_kp = f"{keypath}.style"
        fill = self._color(
            s.get("fill"), context, template, node_id, keypath, "fill", line_of(s, "fill")
        )
        stroke = self._color(
            s.get("stroke"), context, template, node_id, keypath, "stroke", line_of(s, "stroke")
        )
        text_color = self._color(
            s.get("color"), context, template, node_id, keypath, "color", line_of(s, "color")
        )
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
        font = s.get("font")
        if isinstance(font, str):
            families: tuple[str, ...] = (font,)
        elif isinstance(font, list):
            families = tuple(str(f) for f in font)
        else:
            families = ()
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
    ) -> str:
        if not isinstance(raw, str):
            return str(raw)
        try:
            value = render_value(raw, context, self._functions)
        except MissingVariableError as exc:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-014",
                    f"Node {node_id!r} references undefined variable '{exc.path}'",
                    file=str(template),
                    keypath=keypath,
                    line=line,
                    hint=f"Declare '{exc.path}' in variables and supply it, or use | default(...).",
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
                    hint="Check the '{{ … }}' expression syntax.",
                )
            ) from exc
        if isinstance(value, str):
            return value
        from arcavex.services.template.expressions import stringify

        return stringify(value)


# ------------------------------------------------------------------- module helpers
# Iteration cap for structural 'repeat' (spec §4.1.2). Exceeding it is a resource error.
_REPEAT_CAP = 1000

# Sentinel returned by type checking to mean "value unchanged" (distinct from None, which is
# a legitimate coerced value the caller may want to keep).
_UNCHANGED = object()

# Template-level sections still deferred to later phases. Authoring one is a located error,
# not a silent no-op. Per RR-4 these are collected together rather than raised on the first.
_UNSUPPORTED_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("styles", "ARC-TPL-093", "Style-pack definitions arrive in Phase 3."),
    ("style", "ARC-TPL-094", "Opting into a style pack arrives in Phase 3."),
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
    formats = raw.get("formats")
    if isinstance(formats, dict):
        for fmt_name, spec in formats.items():
            if isinstance(spec, dict) and "patch" in spec:
                out.append(
                    diagnostic(
                        "ARC-TPL-095",
                        f"Per-format 'patch' on format {fmt_name!r} is not supported "
                        "in this build",
                        file=str(source.file_for("formats")),
                        keypath=f"formats.{fmt_name}.patch",
                        line=line_of(spec, "patch"),
                        hint="Format patch operations arrive in Phase 2.",
                    )
                )
    return out


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


def _parse_size_required(
    value: Any, dpi: int, template: Path, node_id: str, keypath: str, axis: str, line: int | None
) -> SizeSpec:
    """Parse a size for one axis; a missing value is an under-constraint, not a fill."""
    if value is None:
        raise DiagnosticError(
            diagnostic(
                "ARC-LAY-032",
                f"Node {node_id!r} is under-constrained: no {axis!r} size given",
                file=str(template),
                keypath=f"{keypath}.constraints.size.{axis}",
                line=line,
                hint="Give this axis a size: fixed (e.g. 100px), a %, 'fill', or 'fit_content'.",
            )
        )
    return _parse_size(value, dpi, template, node_id, keypath, axis, line)


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
    line: int | None = None,
) -> AnchorEdge:
    text = value.strip()
    if not text.startswith("parent."):
        raise DiagnosticError(
            diagnostic(
                "ARC-LAY-011",
                f"Node {node_id!r} anchor {key!r} must reference a parent edge",
                file=str(template),
                keypath=f"{keypath}.constraints.anchor.{key}",
                line=line,
                hint="Write anchors like 'parent.top' or 'parent.left+20pt'.",
            )
        )
    rest = text[len("parent.") :]
    offset_pt = 0.0
    edge = rest
    for sign_char in ("+", "-"):
        idx = rest.find(sign_char)
        if idx > 0:
            edge = rest[:idx].strip()
            # Tolerate whitespace around the sign and value ('parent.left + 40px'); the
            # offset grammar should not be stricter than the expression grammar (DX).
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
                        hint="Offsets look like '+20px', '+20pt', or '-6mm'.",
                    )
                ) from exc
            break
    edge = edge.strip()
    if edge not in _PARENT_EDGES:
        raise DiagnosticError(
            diagnostic(
                "ARC-LAY-013",
                f"Node {node_id!r} anchor {key!r} references unknown parent edge {edge!r}",
                file=str(template),
                keypath=f"{keypath}.constraints.anchor.{key}",
                line=line,
                hint=f"Parent edges are: {', '.join(sorted(_PARENT_EDGES))}.",
            )
        )
    return AnchorEdge(edge=edge, offset_pt=offset_pt)  # type: ignore[arg-type]

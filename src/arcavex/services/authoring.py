"""Template authoring service: scaffold, inspect, and split (spec §6.1.3).

These operations back ``arcavex template new/inspect/split``. They call the same compiler the
render path uses, so an inspected contract cannot drift from what actually compiles. The
service returns versioned kernel response models and never raises across the facade boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arcavex.kernel.api import (
    CompilerProtocol,
    FormatInfo,
    FunctionInfo,
    LocaleInfo,
    NodeInfo,
    PatchOp,
    PatchTemplateResult,
    ScaffoldResult,
    SplitResult,
    TemplateInspectReport,
    VariableInfo,
)
from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic, has_errors
from arcavex.kernel.ir.models import SourceRef
from arcavex.kernel.ir.units import Dim
from arcavex.services.fsutil import sha256_bytes
from arcavex.services.template.compiler import (
    _CONSTRAINT_KEYS,
    _FIT_KEYS,
    _PARAGRAPH_KEYS,
    _SIZE_MAP_KEYS,
    _STYLE_KEYS,
)
from arcavex.services.template.functions import FUNCTION_SIGNATURES
from arcavex.services.template.loader import (
    _SIDECARS,
    TemplateSource,
    dump_yaml,
    line_of,
    load_template,
    load_yaml,
    node_line,
    resolve_template_path,
)
from arcavex.services.template.overlays import (
    TEMPLATE_PATCH_ROOTS,
    PatchLog,
    apply_patches,
)

# Blocks whose fields have a fixed vocabulary the compiler validates at compile time. A patch
# 'set'/'insert' whose leaf lands in one of these blocks is field-checked before the write, so a
# typo (fontsize vs font_size) is a located ARC-TPL-051 in the patch response itself rather than
# a silent write that only surfaces on the next validate (DX-4). Reuses the compiler's own
# whitelists so the two checks can never diverge. Anchor edges and node-level fields have an
# open/contextual vocabulary and are left to the compiler's full validation, so this check never
# rejects a genuinely-valid edit.
_PATCH_FIELD_SCHEMA: dict[str, frozenset[str]] = {
    "style": _STYLE_KEYS,
    "fit": _FIT_KEYS,
    "paragraph": _PARAGRAPH_KEYS,
    "constraints": _CONSTRAINT_KEYS,
}

# The sections a one-file template splits into, mapped to their sidecar filename. Mirrors the
# loader's merge so a split template loads back to identical content.
_SPLIT_MAP: tuple[tuple[str, str], ...] = (
    ("variables", "schema.yaml"),
    ("formats", "formats.yaml"),
    ("locales", "locales.yaml"),
    ("preview_data", "preview-data.yaml"),
)


@dataclass(frozen=True)
class AuthoredEffect:
    """One source effect declaration before compiler parameter normalization."""

    name: str
    params: dict[str, object]


@dataclass(frozen=True)
class AuthoredMask:
    """One source mask declaration before compiler parameter normalization."""

    component: str
    params: dict[str, object]


@dataclass(frozen=True)
class AuthoredLayer:
    """Source-only layer definition; structural constructs remain unexpanded."""

    id: str
    kind: str
    #: Authored text for a text node; None for every other kind.
    text: str | None
    #: The node's authored ``style`` mapping, so an editor can show what it is about to change
    #: rather than writing blind. Plain values only; absent when the node declares no style.
    style: dict[str, Any] | None
    #: The node's authored ``paragraph`` mapping (``align``, ``direction``). Separate from style
    #: because the text renderer reads alignment from here, and an editor writing it to ``style``
    #: produces a value the schema accepts and the renderer ignores.
    paragraph: dict[str, Any] | None
    parent_id: str | None
    authored_index: int
    z: int
    visible: bool
    origin: str
    condition: str | None
    collection: str | None
    loop_var: str | None
    key: str | None
    file: str
    keypath: str
    line: int | None
    effects: tuple[AuthoredEffect, ...]
    mask: AuthoredMask | None
    children: tuple[AuthoredLayer, ...]

_SCAFFOLD_TEMPLATE = """\
version: 0.1.0

# A minimal, self-contained card that renders out of the box (no external assets).
variables:
  title: {type: string, required: true, doc: "Main headline shown large"}
  subtitle: {type: string, required: false, doc: "Optional supporting line"}
  # An optional variable with no default reads as none when omitted, which the `if:` below
  # tests. Set `badge:` in data.yaml to make the footer appear.
  badge: {type: string, required: false, doc: "Optional corner badge; shows the footer when set"}

formats:
  square:
    canvas: {width: 1080px, height: 1080px, dpi: 96}
  story:
    canvas: {width: 1080px, height: 1920px, dpi: 96}

# Used when no --data file is supplied, so `render <dir> --format square` works immediately.
preview_data:
  title: "My Card"

root:
  type: group
  id: root
  children:
    - id: background
      type: shape
      shape: rect
      style: {fill: "#0f1020"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}

    - id: accent
      type: shape
      shape: rrect
      style: {fill: "#3ddc97", corner_radius: 8px}
      constraints:
        anchor: {top: parent.center_y-140px, left: parent.left+64px}
        size: {w: 180px, h: 12px}

    - id: title
      type: text
      text: "{{ title }}"
      style: {font: Inter, font_size: 84px, font_weight: 800, color: "#ffffff", align: start}
      constraints:
        anchor: {left: parent.left+64px, top: parent.center_y-60px}
        size: {w: 82%, h: fit_content}

    - id: subtitle
      type: text
      # The `| default(...)` operator supplies a fallback when subtitle is omitted.
      text: "{{ subtitle | default('Edit data.yaml to change me') }}"
      style: {font: Inter, font_size: 36px, color: "#b9f5d8", align: start}
      constraints:
        anchor: {left: parent.left+64px, top: parent.center_y+70px}
        size: {w: 82%, h: fit_content}

    # Conditional node: included only when `badge` is supplied. `if:` is fully usable today
    # because this single node has its own distinct anchor. (Laying out a *dynamic* number of
    # repeated nodes needs layout stacks, which arrive in Phase 2 — see the template README.)
    - if: "{{ badge is not none }}"
      node:
        id: badge
        type: text
        text: "{{ badge }}"
        style: {font: Inter, font_size: 28px, font_weight: 600, color: "#3ddc97", align: start}
        constraints:
          anchor: {left: parent.left+64px, bottom: parent.bottom-64px}
          size: {w: 82%, h: fit_content}
"""

_SCAFFOLD_DATA = """\
title: "Hello from Arcavex"
subtitle: "A scaffolded card"
# Uncomment to make the conditional footer appear:
# badge: "NEW"
"""


def _scaffold_readme(name: str) -> str:
    return f"""\
# {name}

A scaffolded Arcavex template.

Render it with the sample data (edit `data.yaml` and re-run to see changes):

```
arcavex render {name} --data {name}/data.yaml --format square -o {name}.png
```

Omitting `--data` renders the `preview_data` baked into `template.yaml` instead, so
`arcavex render {name} --format square` also works out of the box.

Start the save-to-preview loop (re-renders on every save):

```
arcavex preview {name}/template.yaml --data {name}/data.yaml --format square --watch
```

Check it without data, or inspect the machine-readable contract:

```
arcavex template check {name}
arcavex template inspect {name} --json
```

## What this template shows

- `{{{{ subtitle | default('…') }}}}` — an optional variable with a fallback.
- `if: "{{{{ badge is not none }}}}"` — a conditional node. Set `badge:` in `data.yaml` to
  make the footer appear; leave it out and the node is dropped.

For the full feature set (repeat, all template functions, split layout, `doctor`, `explain`),
see the top-level project README.
"""


class AuthoringService:
    """Implements scaffold/inspect/split using the shared compiler and loader."""

    def __init__(self, compiler: CompilerProtocol, function_names: list[str]) -> None:
        """Wire the authoring service.

        Args:
            compiler: The template compiler (used to compile for inspect).
            function_names: The registered template-function names, for inspect output.
        """
        self._compiler = compiler
        self._functions = sorted(function_names)

    # ---------------------------------------------------------------------- new
    def scaffold(self, name: str, target: Path) -> ScaffoldResult:
        """Create a minimal renderable one-file template directory at ``target``."""
        target = Path(target)
        if target.exists() and any(target.iterdir()):
            return ScaffoldResult(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-TPL-070",
                        f"Scaffold target already exists and is not empty: {target}",
                        file=str(target),
                        hint="Choose a new directory name, or remove the existing one.",
                    )
                ],
            )
        display_name = target.name or name
        target.mkdir(parents=True, exist_ok=True)
        (target / "template.yaml").write_text(_SCAFFOLD_TEMPLATE, encoding="utf-8")
        (target / "data.yaml").write_text(_SCAFFOLD_DATA, encoding="utf-8")
        (target / "README.md").write_text(_scaffold_readme(display_name), encoding="utf-8")
        return ScaffoldResult(
            ok=True,
            path=str(target),
            format="square",
            files=["template.yaml", "data.yaml", "README.md"],
        )

    # ------------------------------------------------------------------ inspect
    def inspect(self, template: Path) -> TemplateInspectReport:
        """Report a template's authored contract: variables, formats, nodes, functions, data.

        Nodes are reported *as authored* (DX-3): ``repeat``/``if`` constructs appear once with
        their origin and expression, never expanded against preview data, so the structural
        contract is complete regardless of what the preview data instantiates. The template is
        still compiled to detect and surface failures (CR-6): a compile error sets ``ok`` and
        ``compiled`` false and the reason rides in ``diagnostics``.
        """
        source = load_template(template)
        raw = source.raw
        variables = _variable_infos(raw.get("variables"))
        formats, fmt_diags = _format_infos(raw.get("formats"))
        locales = _locale_infos(raw.get("locales"))
        preview_data = _to_plain(raw.get("preview_data") or {})
        version = raw.get("version")
        version_str = str(version) if version is not None else None
        nodes = _walk_authored_nodes(raw.get("root"))

        format_name = formats[0].name if formats else None
        result = self._compiler.compile(template, None, format_name, None, None)
        diagnostics: list[Diagnostic] = []
        for diag in [*fmt_diags, *result.diagnostics]:
            if diag not in diagnostics:
                diagnostics.append(diag)
        compiled = result.document is not None and not has_errors(result.diagnostics)
        return TemplateInspectReport(
            ok=not has_errors(diagnostics),
            compiled=compiled,
            version=version_str,
            is_split=source.is_split,
            variables=variables,
            formats=formats,
            locales=locales,
            nodes=nodes,
            functions=_function_infos(self._functions),
            preview_data=preview_data if isinstance(preview_data, dict) else {},
            diagnostics=diagnostics,
        )

    def authored_layer_tree(
        self,
        template: Path,
        *,
        effective_root: Any | None = None,
        source_map: dict[int, SourceRef] | None = None,
    ) -> AuthoredLayer | None:
        """Project a compiler-effective hierarchy without evaluating structural constructs."""
        if effective_root is None:
            source = load_template(template)
            effective_root = source.raw.get("root")
            fallback_file = str(source.file_for("root"))
        else:
            root_source = (source_map or {}).get(id(effective_root))
            fallback_file = (
                str(template / "template.yaml") if Path(template).is_dir() else str(template)
            )
            if root_source is not None and root_source.file is not None:
                fallback_file = root_source.file
        return _authored_layer(
            effective_root,
            parent_id=None,
            authored_index=0,
            origin="static",
            construct={},
            file=fallback_file,
            keypath="root",
            source_map=source_map or {},
        )

    # -------------------------------------------------------------------- split
    def split(self, template: Path) -> SplitResult:
        """Convert a one-file template into a split directory, preserving comments."""
        root_dir, template_yaml = resolve_template_path(template)
        # Refuse if already split: any sidecar present means the split has been done.
        for filename, _section in _SIDECARS:
            if (root_dir / filename).is_file():
                return SplitResult(
                    ok=False,
                    directory=str(root_dir),
                    diagnostics=[
                        diagnostic(
                            "ARC-TPL-071",
                            f"Template is already split (found {filename!r})",
                            file=str(root_dir),
                            hint="Sidecar files already exist; nothing to split.",
                        )
                    ],
                )
        raw = load_yaml(template_yaml)
        if not hasattr(raw, "get"):
            return SplitResult(
                ok=False,
                directory=str(root_dir),
                diagnostics=[
                    diagnostic(
                        "ARC-TPL-003",
                        "Template root must be a mapping",
                        file=str(template_yaml),
                        hint="Only a mapping-shaped template can be split.",
                    )
                ],
            )
        written: list[str] = []
        for section, filename in _SPLIT_MAP:
            if section in raw:
                dump_yaml(raw[section], root_dir / filename)
                del raw[section]
                written.append(filename)
        dump_yaml(raw, template_yaml)
        written.append("template.yaml")
        return SplitResult(ok=True, directory=str(root_dir), files=written)

    # -------------------------------------------------------------------- patch
    def patch_template(
        self, template: Path, ops: list[PatchOp], base_sha256: str | None = None
    ) -> PatchTemplateResult:
        """Apply path-addressed patch ops to a template on disk, preserving comments.

        The ops reuse the exact ``set/remove/insert_*`` grammar the override layers use
        (``services.template.overlays``) and may address the node tree (``nodes.<id>...``) or,
        because this is the top-level operation and not an embedded layer, the template's own
        sections: ``formats.<name>``, ``variables.<name>``, ``preview_data.<key>``,
        ``locales.<name>`` (each with an optional field path, list indexes included) and the
        whole ``style`` value. Insert verbs stay node-only. The file is written back through
        ruamel round-trip so comments and key order survive; on a split template each section
        is written to the sidecar that holds it.

        An op that does not name exactly one verb (``ARC-TPL-092``, CR-1) or whose leaf field is
        unknown for a fixed-vocabulary block (``ARC-TPL-051``, DX-4) is rejected *before* the
        write, so an ambiguous op never applies partially and a typo'd field never silently
        lands. An unknown addressed path raises a located ``ARC-TPL-092``. After the write the
        template is compiled for every declared format, and a patch that *introduces* a compile
        error (a canvas that does not parse, a removed value a required variable needs, an
        unknown style pack) is rolled back and refused with those located diagnostics — errors
        the template already had do not block an unrelated edit, so a broken template can still
        be repaired one op at a time. A stale ``base_sha256`` (the file changed on disk since the
        agent read it) is refused with ``ARC-TPL-110`` before anything is written, so a
        concurrent edit is never overwritten (spec §8.3). Never raises.
        """
        try:
            _root_dir, template_yaml = resolve_template_path(template)
        except DiagnosticError as exc:
            return PatchTemplateResult(ok=False, diagnostics=list(exc.diagnostics))
        current_sha = sha256_bytes(template_yaml.read_bytes())
        if base_sha256 is not None and base_sha256 != current_sha:
            return PatchTemplateResult(
                ok=False,
                path=str(template_yaml),
                sha256=current_sha,
                diagnostics=[
                    diagnostic(
                        "ARC-TPL-110",
                        "Template changed on disk since it was read; patch not applied",
                        file=str(template_yaml),
                        hint="Re-inspect the template to get its current hash, rebase your edit "
                        "on it, and retry — another writer changed the file.",
                    )
                ],
            )
        # Boundary validation (CR-1/DX-4): reject ambiguous ops and typo'd leaf fields before any
        # write, so a malformed patch is a located diagnostic, never a partial or silent mutation.
        op_diags = _validate_patch_ops(ops, template_yaml)
        if has_errors(op_diags):
            return PatchTemplateResult(
                ok=False, path=str(template_yaml), sha256=current_sha, diagnostics=op_diags
            )
        try:
            source = load_template(template_yaml)
            raw = source.raw
            root_map = raw.get("root")
            if not hasattr(root_map, "get"):
                return PatchTemplateResult(
                    ok=False,
                    path=str(template_yaml),
                    sha256=current_sha,
                    diagnostics=[
                        diagnostic(
                            "ARC-TPL-004",
                            "Template has no 'root' node to patch",
                            file=str(template_yaml),
                            hint="A patchable template defines a 'root:' group node.",
                        )
                    ],
                )
            # Errors the template already has are not the patch's doing: only errors the patch
            # introduces refuse it, so an author can repair a broken template one op at a time.
            already = {
                _diag_key(d)
                for d in self._compile_errors(template_yaml, _format_names(raw.get("formats")))
            }
            plain_ops = [op.to_patch_dict() for op in ops]
            apply_patches(
                root_map, plain_ops, "patch", template_yaml, "patch", PatchLog(),
                allowed_roots=TEMPLATE_PATCH_ROOTS, document=raw,
            )
        except DiagnosticError as exc:
            return PatchTemplateResult(
                ok=False, path=str(template_yaml), sha256=current_sha,
                diagnostics=list(exc.diagnostics),
            )
        # Read the patched format list before the write: writing a split template moves each
        # sidecar section out of the merged mapping.
        formats_after = _format_names(raw.get("formats"))
        snapshot = {
            path: path.read_bytes()
            for path in {template_yaml, *source.section_files.values()}
        }
        try:
            _write_template_source(source)
            introduced = [
                d
                for d in self._compile_errors(template_yaml, formats_after)
                if _diag_key(d) not in already
            ]
        except Exception:
            _restore_files(snapshot)
            raise
        if introduced:
            _restore_files(snapshot)
            return PatchTemplateResult(
                ok=False, path=str(template_yaml), sha256=current_sha, diagnostics=introduced
            )
        new_sha = sha256_bytes(template_yaml.read_bytes())
        return PatchTemplateResult(
            ok=True, path=str(template_yaml), sha256=new_sha, applied=len(ops)
        )

    def _compile_errors(self, template_yaml: Path, formats: list[str]) -> list[Diagnostic]:
        """Return the error diagnostics of compiling the template for each declared format.

        With no formats declared the single compile reports that (``ARC-TPL-020``) — a template
        a patch left without a canvas is as unrenderable as one with a canvas that does not parse.
        """
        errors: list[Diagnostic] = []
        for fmt in formats or [None]:
            try:
                result = self._compiler.compile(template_yaml, None, fmt, None, None)
            except DiagnosticError as exc:
                errors.extend(d for d in exc.diagnostics if d.is_error())
                continue
            errors.extend(d for d in result.diagnostics if d.is_error())
        return errors


def _format_names(formats: Any) -> list[str]:
    return [str(name) for name in formats] if isinstance(formats, dict) else []


def _diag_key(diag: Diagnostic) -> tuple[str, str, str | None]:
    """The identity of a compile error for before/after comparison: code, message, keypath."""
    keypath = diag.source.keypath if diag.source is not None else None
    return diag.code, diag.message, keypath


def _write_template_source(source: TemplateSource) -> None:
    """Write a (possibly split) template back: each sidecar section to its file, the rest inline.

    ``load_template`` merges sidecar sections into the ``template.yaml`` mapping, so they are
    written out to their own files and removed from the mapping before it is dumped — otherwise
    a split template would come back with every section defined twice (``ARC-TPL-097``).
    """
    raw = source.raw
    for section, sidecar in source.section_files.items():
        if section in raw:
            dump_yaml(raw[section], sidecar)
            del raw[section]
    dump_yaml(raw, source.template_path)


def _restore_files(snapshot: dict[Path, bytes]) -> None:
    for path, content in snapshot.items():
        path.write_bytes(content)


def _patch_verbs(op: PatchOp) -> list[str]:
    """Return the verb fields this op actually names (should be exactly one)."""
    return [
        verb
        for verb in ("set", "remove", "insert_before", "insert_after")
        if getattr(op, verb) is not None
    ]


def _validate_patch_ops(ops: list[PatchOp], template_yaml: Path) -> list[Diagnostic]:
    """Validate patch ops at the boundary before any write (CR-1 verb count, DX-4 leaf field).

    Returns located diagnostics; an empty list (or warnings only) means the ops are safe to
    apply. Each op must name exactly one verb, and a ``set`` whose leaf lands in a
    fixed-vocabulary block (style/fit/paragraph/constraints) must use a known field name —
    reusing the compiler's own whitelists so this never diverges from what ``validate`` accepts.
    """
    diags: list[Diagnostic] = []
    for i, op in enumerate(ops):
        kp = f"patch[{i}]"
        verbs = _patch_verbs(op)
        if len(verbs) != 1:
            named = ", ".join(verbs) or "(none)"
            diags.append(
                diagnostic(
                    "ARC-TPL-092",
                    "Invalid patch operation: each op needs exactly one of "
                    f"set/remove/insert_before/insert_after (got: {named})",
                    file=str(template_yaml),
                    keypath=kp,
                    hint="Split multiple mutations into separate ops; each op does one thing.",
                )
            )
            continue
        verb = verbs[0]
        if verb == "set":
            leaf = _leaf_field_diag(op.set, template_yaml)
            if leaf is not None:
                diags.append(leaf)
    return diags


def _leaf_field_diag(path: str | None, template_yaml: Path) -> Diagnostic | None:
    """Return an ARC-TPL-051 if ``path``'s leaf is an unknown field of a fixed-vocabulary block.

    Addresses ``nodes.<id>.<block>.<field>`` (and ``constraints.size.<axis>.<field>``). Only the
    blocks in :data:`_PATCH_FIELD_SCHEMA` (plus the size sub-map) have a closed vocabulary; any
    other target — a node-level field, an anchor edge — is left to the compiler's full validation
    so a valid edit is never rejected here.
    """
    if not isinstance(path, str) or not path.startswith("nodes."):
        return None
    parts = path.split(".")
    node_id, segments = (parts[1] if len(parts) > 1 else "?"), parts[2:]
    if len(segments) < 2:
        return None
    block = segments[0]
    if block == "constraints" and len(segments) >= 4 and segments[1] == "size":
        # nodes.<id>.constraints.size.<axis>.<field>
        return _unknown_field_diag(
            node_id, "size", segments[-1], _SIZE_MAP_KEYS, path, template_yaml
        )
    allowed = _PATCH_FIELD_SCHEMA.get(block)
    if allowed is None or len(segments) != 2:
        return None
    return _unknown_field_diag(node_id, block, segments[1], allowed, path, template_yaml)


def _unknown_field_diag(
    node_id: str,
    block: str,
    field: str,
    allowed: frozenset[str],
    path: str,
    template_yaml: Path,
) -> Diagnostic | None:
    if field in allowed:
        return None
    valid = ", ".join(sorted(allowed))
    return diagnostic(
        "ARC-TPL-051",
        f"Node {node_id!r} has unknown {block} field {field!r}",
        file=str(template_yaml),
        keypath=path,
        hint=f"Valid {block} fields are: {valid}.",
    )


def _variable_infos(variables: Any) -> list[VariableInfo]:
    if not isinstance(variables, dict):
        return []
    out: list[VariableInfo] = []
    for name, decl in variables.items():
        decl = decl if isinstance(decl, dict) else {}
        enum = decl.get("enum")
        out.append(
            VariableInfo(
                name=str(name),
                type=decl.get("type"),
                required=bool(decl.get("required", False)),
                has_default="default" in decl,
                default=_to_plain(decl["default"]) if "default" in decl else None,
                doc=decl.get("doc"),
                enum=[_to_plain(e) for e in enum] if isinstance(enum, list) else None,
            )
        )
    return out


def _format_infos(formats: Any) -> tuple[list[FormatInfo], list[Diagnostic]]:
    if not isinstance(formats, dict):
        return [], []
    out: list[FormatInfo] = []
    diags: list[Diagnostic] = []
    for name, spec in formats.items():
        canvas = spec.get("canvas") if isinstance(spec, dict) else None
        if not isinstance(canvas, dict):
            continue
        raw_w, raw_h = canvas.get("width"), canvas.get("height")
        try:
            dpi = int(canvas.get("dpi", 96))
            width = Dim.parse(raw_w).to_pt(dpi)
            height = Dim.parse(raw_h).to_pt(dpi)
        except (ValueError, TypeError):
            diags.append(
                diagnostic(
                    "ARC-IR-011",
                    f"Format {name!r} has an invalid canvas dimension",
                    keypath=f"formats.{name}.canvas",
                    line=line_of(formats, str(name)),
                    hint="Use numbers with units: px, pt, or mm.",
                )
            )
            continue
        out.append(
            FormatInfo(
                name=str(name),
                width=str(raw_w) if raw_w is not None else None,
                height=str(raw_h) if raw_h is not None else None,
                width_pt=width,
                height_pt=height,
                dpi=dpi,
            )
        )
    return out, diags


def _locale_infos(locales: Any) -> list[LocaleInfo]:
    """Report each declared locale's direction/digits and whether it remaps fonts or patches.

    Spec §4.1.1 requires inspect to expose locales so an AI learns the template's locale
    contract without guessing a name and reading an ``ARC-TPL-100``. Shape validation stays in
    the compiler (``ARC-TPL-098``/``ARC-TPL-099``); this projection is best-effort and simply
    skips a malformed entry rather than raising.
    """
    if not isinstance(locales, dict):
        return []
    out: list[LocaleInfo] = []
    for name, settings in locales.items():
        settings = settings if isinstance(settings, dict) else {}
        out.append(
            LocaleInfo(
                name=str(name),
                direction=_str_or_none(settings.get("direction")),
                digits=_str_or_none(settings.get("digits")),
                has_fonts=isinstance(settings.get("fonts"), dict) and bool(settings.get("fonts")),
                has_patch=isinstance(settings.get("patch"), list) and bool(settings.get("patch")),
            )
        )
    return out


def _function_infos(names: list[str]) -> list[FunctionInfo]:
    """Build inspect's function list with a signature and one-line doc for each name (DX-3)."""
    out: list[FunctionInfo] = []
    for name in sorted(names):
        signature, doc = FUNCTION_SIGNATURES.get(name, (f"{name}(…)", None))
        out.append(FunctionInfo(name=name, signature=signature, doc=doc))
    return out


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _authored_layer(
    node_raw: Any,
    *,
    parent_id: str | None,
    authored_index: int,
    origin: str,
    construct: dict[str, str | None],
    file: str,
    keypath: str,
    source_map: dict[int, SourceRef],
) -> AuthoredLayer | None:
    """Project one authored node while preserving wrappers instead of evaluating them."""
    if not isinstance(node_raw, dict):
        return None
    mapped_source = source_map.get(id(node_raw))
    node_file = file
    node_keypath = keypath
    node_source_line: int | None = None
    if mapped_source is not None:
        node_file = mapped_source.file or node_file
        node_keypath = mapped_source.keypath or node_keypath
        node_source_line = mapped_source.line
    node_id = _str_or_none(node_raw.get("id")) or "?"
    effects: list[AuthoredEffect] = []
    raw_effects = node_raw.get("effects")
    if isinstance(raw_effects, list):
        for raw_effect in raw_effects:
            if not isinstance(raw_effect, dict):
                continue
            params = _to_plain(raw_effect.get("params") or {})
            effects.append(
                AuthoredEffect(
                    name=_str_or_none(raw_effect.get("name")) or "?",
                    params=params if isinstance(params, dict) else {},
                )
            )
    mask: AuthoredMask | None = None
    raw_mask = node_raw.get("mask")
    if isinstance(raw_mask, dict):
        params = _to_plain(raw_mask.get("params") or {})
        mask = AuthoredMask(
            component=_str_or_none(raw_mask.get("component")) or "?",
            params=params if isinstance(params, dict) else {},
        )
    children: list[AuthoredLayer] = []
    raw_children = node_raw.get("children")
    if isinstance(raw_children, list):
        for index, child in enumerate(raw_children):
            child_keypath = f"{node_keypath}.children[{index}]"
            child_node = child
            child_origin = "static"
            child_construct: dict[str, str | None] = {}
            if isinstance(child, dict) and "repeat" in child and "node" in child:
                child_node = child["node"]
                child_origin = "repeat"
                child_construct = {
                    "collection": _str_or_none(child.get("repeat")),
                    "loop_var": _str_or_none(child.get("as")),
                    "key": _str_or_none(child.get("key")),
                }
                child_keypath = f"{child_keypath}.node"
            elif isinstance(child, dict) and "if" in child and "node" in child:
                child_node = child["node"]
                child_origin = "if"
                child_construct = {"condition": _str_or_none(child.get("if"))}
                child_keypath = f"{child_keypath}.node"
            projected = _authored_layer(
                child_node,
                parent_id=node_id,
                authored_index=index,
                origin=child_origin,
                construct=child_construct,
                file=file,
                keypath=child_keypath,
                source_map=source_map,
            )
            if projected is not None:
                children.append(projected)
    raw_z = node_raw.get("z", 0)
    z = raw_z if isinstance(raw_z, int) and not isinstance(raw_z, bool) else 0
    raw_visible = node_raw.get("visible", True)
    return AuthoredLayer(
        id=node_id,
        kind=_str_or_none(node_raw.get("type")) or "?",
        text=_str_or_none(node_raw.get("text")),
        style=_plain_mapping(node_raw.get("style")),
        paragraph=_plain_mapping(node_raw.get("paragraph")),
        parent_id=parent_id,
        authored_index=authored_index,
        z=z,
        visible=raw_visible if isinstance(raw_visible, bool) else True,
        origin=origin,
        condition=construct.get("condition"),
        collection=construct.get("collection"),
        loop_var=construct.get("loop_var"),
        key=construct.get("key"),
        file=node_file,
        keypath=node_keypath,
        line=node_source_line or line_of(node_raw, "id") or node_line(node_raw),
        effects=tuple(effects),
        mask=mask,
        children=tuple(children),
    )


def _walk_authored_nodes(root_raw: Any) -> list[NodeInfo]:
    """Walk the authored node tree, reporting repeat/if constructs unexpanded (DX-3)."""
    out: list[NodeInfo] = []

    def visit_node(node_raw: Any, origin: str, meta: dict[str, str | None]) -> None:
        if not isinstance(node_raw, dict):
            return
        out.append(
            NodeInfo(
                id=_str_or_none(node_raw.get("id")) or "?",
                type=_str_or_none(node_raw.get("type")) or "?",
                origin=origin,  # type: ignore[arg-type]
                **meta,
            )
        )
        children = node_raw.get("children")
        if isinstance(children, list):
            for child in children:
                visit_child(child)

    def visit_child(child: Any) -> None:
        if not isinstance(child, dict):
            return
        if "repeat" in child and "node" in child:
            visit_node(
                child["node"],
                "repeat",
                {
                    "collection": _str_or_none(child.get("repeat")),
                    "loop_var": _str_or_none(child.get("as")),
                    "key": _str_or_none(child.get("key")),
                },
            )
        elif "if" in child and "node" in child:
            visit_node(child["node"], "if", {"condition": _str_or_none(child.get("if"))})
        else:
            visit_node(child, "static", {})

    visit_node(root_raw, "static", {})
    return out


def _to_plain(obj: Any) -> Any:
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


def raise_if_missing(template: Path) -> None:
    """Raise a located diagnostic if ``template`` cannot be resolved (used by the CLI)."""
    if not Path(template).exists():
        raise DiagnosticError(
            diagnostic(
                "ARC-TPL-001",
                f"Template not found: {template}",
                file=str(template),
                hint="Check the path on the command line.",
            )
        )


def _plain_mapping(value: Any) -> dict[str, Any] | None:
    """A YAML mapping as plain Python, or None when the node declares none."""
    if not isinstance(value, dict) or not value:
        return None
    plain: dict[str, Any] = {}
    for key, item in value.items():
        plain[str(key)] = (
            _plain_mapping(item) if isinstance(item, dict) else _plain_scalar(item)
        )
    return plain


def _plain_scalar(value: Any) -> Any:
    """Unwrap a ruamel scalar to the JSON-safe value underneath it."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_plain_scalar(item) for item in value]
    return str(value)

"""Template authoring service: scaffold, inspect, and split (spec §6.1.3).

These operations back ``arcavex template new/inspect/split``. They call the same compiler the
render path uses, so an inspected contract cannot drift from what actually compiles. The
service returns versioned kernel response models and never raises across the facade boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

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
    _ROOT_KEYS,
    _SIZE_MAP_KEYS,
    _STYLE_KEYS,
)
from arcavex.services.template.functions import FUNCTION_SIGNATURES
from arcavex.services.template.loader import (
    _SIDECARS,
    dump_yaml,
    line_of,
    load_template,
    load_yaml,
    node_line,
    resolve_template_path,
)
from arcavex.services.template.overlays import PatchLog, apply_patches

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

# The patch verbs, in the order ``PatchOp.to_patch_dict`` emits them. Kept in one place so the
# boundary validator, the scoped upsert, and the addressed-path reader stay in lockstep.
_PATCH_VERBS: tuple[str, ...] = ("set", "remove", "insert_before", "insert_after")


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
#
# Constructs this build accepts (anything else fails validation with the code shown;
# `arcavex explain <code>` prints the fix):
#   shape:            rect | rrect | circle | ellipse, or generator: starburst | speech_bubble
#                     | qr_code                                                   (ARC-TPL-036)
#   numeric style:    font_size, font_weight, stroke_width, corner_radius, letter_spacing and
#                     opacity take literals, a style_role or format/locale patches, never
#                     {{ expressions }}                                           (ARC-TPL-069)
#   mask/effect/shape lengths: pt, mm or px (px converts at the format's dpi)     (ARC-FX-902)
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

locales:
  en: {direction: ltr, digits: en}

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

    # Conditional node: included only when `badge` is supplied. This single node has its own
    # distinct anchor; for blocks of variable height or a dynamic number of repeated nodes, put
    # them in a `layout: vstack` group with a `gap` instead of chaining sibling anchors.
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
        self,
        template: Path,
        ops: list[PatchOp],
        base_sha256: str | None = None,
        *,
        format_name: str | None = None,
        locale: str | None = None,
        unset: bool = False,
    ) -> PatchTemplateResult:
        """Apply path-addressed patch ops to a template file on disk, preserving comments.

        The ops reuse the exact ``set/remove/insert_*`` grammar the override layers use
        (``services.template.overlays``), applied here to ``template.yaml``'s ``root`` AST and
        written back through ruamel round-trip so comments and key order survive. An op that does
        not name exactly one verb (``ARC-TPL-092``, CR-1) or whose leaf field is unknown for a
        fixed-vocabulary block (``ARC-TPL-051``, DX-4) is rejected *before* the write, so an
        ambiguous op never applies partially and a typo'd field never silently lands. An unknown
        addressed path raises a located ``ARC-TPL-092``; a stale ``base_sha256`` (the file changed
        on disk since the agent read it) is refused with ``ARC-TPL-110`` before anything is
        written, so a concurrent edit is never overwritten (spec §8.3). Never raises.

        With ``format_name`` and/or ``locale`` the op is not applied to the root AST but upserted
        into the matching format/locale patch list the compiler applies at render time
        (``formats.<F>.patch``, ``locales.<L>.patch``, or the narrowest
        ``locales.<L>.formats.<F>.patch``) — see :meth:`_patch_scoped_template`, which also
        documents ``unset`` and locale ``fonts.<Family>`` overrides.
        """
        if format_name is None and locale is None:
            return self._patch_root_template(template, ops, base_sha256)
        return self._patch_scoped_template(
            template,
            ops,
            base_sha256,
            format_name=format_name,
            locale=locale,
            unset=unset,
        )

    def _patch_root_template(
        self, template: Path, ops: list[PatchOp], base_sha256: str | None
    ) -> PatchTemplateResult:
        """Apply ops to ``template.yaml``'s ``root`` AST (the unscoped A1..A4 contract)."""
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
            raw = load_yaml(template_yaml)
            root_map = raw.get("root") if hasattr(raw, "get") else None
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
            plain_ops = [op.to_patch_dict() for op in ops]
            for index, op in enumerate(plain_ops):
                verb = next(v for v in ("set", "remove", "insert_before", "insert_after")
                            if v in op)
                path = op[verb]
                if isinstance(path, str) and path.startswith("template."):
                    _patch_section(raw, op, verb, template_yaml)
                else:
                    apply_patches(root_map, [op], "patch", template_yaml,
                                  f"patch[{index}]", PatchLog())
            dump_yaml(raw, template_yaml)
        except DiagnosticError as exc:
            return PatchTemplateResult(
                ok=False, path=str(template_yaml), sha256=current_sha,
                diagnostics=list(exc.diagnostics),
            )
        new_sha = sha256_bytes(template_yaml.read_bytes())
        return PatchTemplateResult(
            ok=True, path=str(template_yaml), sha256=new_sha, applied=len(ops)
        )

    def _patch_scoped_template(
        self,
        template: Path,
        ops: list[PatchOp],
        base_sha256: str | None,
        *,
        format_name: str | None,
        locale: str | None,
        unset: bool,
    ) -> PatchTemplateResult:
        """Upsert ops into a format/locale patch list instead of the root AST (A5).

        ``formats.<F>.patch``, ``locales.<L>.patch``, or the narrowest
        ``locales.<L>.formats.<F>.patch`` — the list the compiler already applies at render time
        (:mod:`services.template.compiler`), so a ``--format square`` edit is stored exactly
        once and affects exactly that format. Locale font overrides use ``fonts.<Family>`` and
        land in ``locales.<L>.fonts``. An op is matched by its addressed path: a second ``set``
        on the same path replaces the value in place rather than appending a duplicate, and
        ``unset`` deletes the matching op.

        The write goes to whichever file *owns* the section: the ``formats.yaml``/``locales.yaml``
        sidecar of a split template, else ``template.yaml`` (:meth:`TemplateSource.file_for`).
        ``base_sha256`` therefore hashes that owning file, not necessarily ``template.yaml``.
        Unlike the root path, a scoped op is deliberately **not** dry-run against the root AST: a
        format/locale op may legally address a field an earlier op in the same list creates, so
        node existence is the compiler's job at validate/render — exactly as it is for a
        hand-authored patch. The fixed-vocabulary leaf check still runs, so a typo'd style field
        is located before the write. Never raises.
        """
        try:
            source = load_template(template)
        except DiagnosticError as exc:
            return PatchTemplateResult(ok=False, diagnostics=list(exc.diagnostics))

        # ``file_for`` is the sidecar of a split template, else template.yaml. Writing anywhere
        # else would leave the section defined twice once the loader merges sidecars (ARC-TPL-097).
        section = "locales" if locale is not None else "formats"
        owning_file = source.file_for(section)
        is_sidecar = owning_file != source.template_path
        current_sha = sha256_bytes(owning_file.read_bytes())
        if base_sha256 is not None and base_sha256 != current_sha:
            return _scoped_error(
                owning_file,
                current_sha,
                None,
                "Template changed on disk since it was read; patch not applied",
                code="ARC-TPL-110",
                hint="Re-inspect the template to get its current hash, rebase your edit on it, "
                "and retry — another writer changed the file.",
            )

        # Grammar sanity before any parse: fonts.<Family> is locale-only, node patches address
        # nodes.*. This keeps an op that could never be applied from being written into a list.
        for op in ops:
            path = _addressed_path(op)
            if path.startswith("fonts."):
                family = path[len("fonts."):]
                if locale is None or format_name is not None:
                    return _scoped_error(
                        owning_file,
                        current_sha,
                        path,
                        "fonts.<Family> is a locale-only patch path",
                        hint="Pass --locale without --format to override locale fonts.",
                    )
                if not family:
                    return _scoped_error(
                        owning_file,
                        current_sha,
                        path,
                        "fonts.<Family> needs a family name",
                        hint="Name the family to override, e.g. --set fonts.Inter.",
                    )
                if op.set is None and op.remove is None:
                    return _scoped_error(
                        owning_file,
                        current_sha,
                        path,
                        "fonts.<Family> accepts set or remove only",
                    )
            elif not path.startswith("nodes."):
                return _scoped_error(
                    owning_file,
                    current_sha,
                    path,
                    f"Scoped patch paths address nodes.* or fonts.*, not {path!r}",
                )

        # Boundary validation (CR-1/DX-4): reject ambiguous ops and typo'd leaf fields before
        # any write, so a malformed patch is a located diagnostic, never a partial mutation.
        op_diags = _validate_patch_ops(ops, owning_file)
        if has_errors(op_diags):
            return PatchTemplateResult(
                ok=False, path=str(owning_file), sha256=current_sha, diagnostics=op_diags
            )

        try:
            # ``source.raw`` has sidecars merged in, so the section node is the same node the
            # loader read from (and will be written back to) the owning file.
            section_map = source.raw.get(section)
            if not isinstance(section_map, dict):
                return _scoped_error(
                    owning_file,
                    current_sha,
                    section,
                    f"Template declares no {section!r} section",
                    hint=f"Add a {section!r} section before patching into it.",
                )

            # Locate the exact target entry before mutating anything: an unknown locale/format is
            # a located error, and because the dump happens only after every op succeeds a refusal
            # leaves the file byte-for-byte unchanged.
            if locale is not None:
                locale_entry = section_map.get(locale)
                if not isinstance(locale_entry, dict):
                    return _scoped_error(
                        owning_file,
                        current_sha,
                        f"locales.{locale}",
                        f"Unknown locale {locale!r}",
                        hint=_declared_names_hint(section_map, "locale"),
                    )
                if format_name is not None:
                    # The compound layer is `locales.<L>.formats.<F>.patch`; F must be a globally
                    # declared format, but the per-locale entry itself is created on demand so a
                    # locale can opt into a per-format override without hand-editing YAML.
                    global_formats = source.raw.get("formats")
                    if not isinstance(global_formats, dict) or format_name not in global_formats:
                        return _scoped_error(
                            owning_file,
                            current_sha,
                            f"formats.{format_name}",
                            f"Unknown format {format_name!r}",
                            hint=_declared_names_hint(global_formats, "format"),
                        )
                    per_format = locale_entry.get("formats")
                    if per_format is not None and not isinstance(per_format, dict):
                        return _scoped_error(
                            owning_file,
                            current_sha,
                            f"locales.{locale}.formats",
                            f"Locale {locale!r} 'formats' must be a mapping",
                        )
            elif format_name is not None and not isinstance(section_map.get(format_name), dict):
                return _scoped_error(
                    owning_file,
                    current_sha,
                    f"formats.{format_name}",
                    f"Unknown format {format_name!r}",
                    hint=_declared_names_hint(section_map, "format"),
                )

            font_ops = [op for op in ops if _addressed_path(op).startswith("fonts.")]
            node_ops = [op for op in ops if not _addressed_path(op).startswith("fonts.")]

            if font_ops:
                locale_entry = section_map[locale]
                fonts = locale_entry.get("fonts")
                if not isinstance(fonts, dict):
                    fonts = CommentedMap()
                    locale_entry["fonts"] = fonts
                for op in font_ops:
                    family = _addressed_path(op).split(".", 1)[1]
                    if unset or op.remove is not None:
                        if family not in fonts:
                            return _scoped_error(
                                owning_file,
                                current_sha,
                                f"locales.{locale}.fonts.{family}",
                                f"No font override to unset for {family!r}",
                            )
                        del fonts[family]
                    else:
                        fonts[family] = op.value

            if node_ops:
                patch_seq = _ensure_patch_seq(section_map, locale, format_name)
                for op in node_ops:
                    if unset:
                        if _remove_matching_ops(patch_seq, _addressed_path(op)) == 0:
                            return _scoped_error(
                                owning_file,
                                current_sha,
                                _addressed_path(op),
                                f"No patch op to unset for {_addressed_path(op)!r}",
                            )
                    else:
                        _upsert_patch_op(patch_seq, op.to_patch_dict())
            if is_sidecar:
                dump_yaml(section_map, owning_file)
            else:
                dump_yaml(source.raw, owning_file)
        except DiagnosticError as exc:
            return PatchTemplateResult(
                ok=False,
                path=str(owning_file),
                sha256=current_sha,
                diagnostics=list(exc.diagnostics),
            )
        return PatchTemplateResult(
            ok=True,
            path=str(owning_file),
            sha256=sha256_bytes(owning_file.read_bytes()),
            applied=len(ops),
        )


def _ensure_patch_seq(
    section_map: Any, locale: str | None, format_name: str | None
) -> CommentedSeq:
    """Return the target entry's ``patch`` sequence, creating missing intermediate nodes."""
    if locale is None:
        entry = section_map[format_name]
    elif format_name is None:
        entry = section_map[locale]
    else:
        per_format = section_map[locale].get("formats")
        if not isinstance(per_format, dict):
            per_format = CommentedMap()
            section_map[locale]["formats"] = per_format
        entry = per_format.get(format_name)
        if not isinstance(entry, dict):
            entry = CommentedMap()
            per_format[format_name] = entry
    patch = entry.get("patch")
    if not isinstance(patch, list):
        patch = CommentedSeq()
        entry["patch"] = patch
    return patch


def _upsert_patch_op(seq: CommentedSeq, op: dict[str, Any]) -> None:
    """Insert ``op``, replacing an existing op that names the same verb and path.

    A second ``set`` on the same path updates the value in place (never appends a duplicate) and
    drops any earlier duplicate, so ``--format square --set …`` is idempotent instead of growing
    an unbounded patch list. That one-op-per-path rule is the whole point of the command.
    """
    verb = next(v for v in _PATCH_VERBS if v in op)
    path = op[verb]
    matches = [
        i
        for i, entry in enumerate(seq)
        if isinstance(entry, dict) and entry.get(verb) == path
    ]
    if not matches:
        seq.append(CommentedMap(op))
        return
    last = matches[-1]
    if verb == "set":
        seq[last]["value"] = op["value"]
    else:
        seq[last] = CommentedMap(op)
    for i in reversed(matches[:-1]):
        del seq[i]


def _remove_matching_ops(seq: CommentedSeq, path: str) -> int:
    """Delete every op addressing ``path`` (any verb) and return how many were removed."""
    removed = 0
    for i in reversed(range(len(seq))):
        entry = seq[i]
        if isinstance(entry, dict) and any(entry.get(v) == path for v in _PATCH_VERBS):
            del seq[i]
            removed += 1
    return removed


def _addressed_path(op: PatchOp) -> str:
    """Return the single path this op addresses, or ``""`` for a verb-less op."""
    for verb in _PATCH_VERBS:
        path = getattr(op, verb)
        if path is not None:
            return str(path)
    return ""


def _declared_names_hint(mapping: Any, kind: str) -> str:
    """List the declared names of ``kind`` so an unknown-target error is self-correcting."""
    if isinstance(mapping, dict) and mapping:
        names = ", ".join(sorted(str(name) for name in mapping))
        return f"Declared {kind}s are: {names}."
    return f"The template declares no {kind}s."


def _scoped_error(
    file: Path,
    sha256: str | None,
    keypath: str | None,
    message: str,
    *,
    code: str = "ARC-TPL-092",
    hint: str | None = None,
) -> PatchTemplateResult:
    """Build a located refusal for a scoped patch; nothing has been written."""
    return PatchTemplateResult(
        ok=False,
        path=str(file),
        sha256=sha256,
        diagnostics=[diagnostic(code, message, file=str(file), keypath=keypath, hint=hint)],
    )


def _patch_section(raw: Any, op: dict[str, Any], verb: str, file: Path) -> None:
    """Set/remove template metadata; node edits keep their existing nodes.<id> grammar."""
    path = op[verb]
    segments = path.split(".")[1:]
    section = segments[0] if segments else ""
    hint = "Use template.<section>[.<field>...] with set/remove; use nodes.<id> for scene edits."

    def fail(message: str) -> None:
        raise DiagnosticError(diagnostic(
            "ARC-TPL-092", message, file=str(file), keypath=path, hint=hint,
        ))

    if verb not in {"set", "remove"} or section not in _ROOT_KEYS - {"root"}:
        fail(f"Unsupported template patch path {path!r}")
    if any((file.parent / filename).is_file() for filename, key in _SIDECARS if key == section):
        fail(f"Section {section!r} lives in a sidecar; edit that sidecar instead")
    target = raw
    for segment in segments[:-1]:
        if not isinstance(target, dict) or segment not in target:
            fail(f"Template patch parent does not exist at {segment!r}")
        target = target[segment]
    if not isinstance(target, dict) or not segments[-1]:
        fail(f"Template patch path {path!r} does not address a mapping field")
    leaf = segments[-1]
    if verb == "remove":
        if leaf not in target:
            fail(f"Template patch field {path!r} does not exist")
        del target[leaf]
    else:
        target[leaf] = op.get("value")


def _patch_verbs(op: PatchOp) -> list[str]:
    """Return the verb fields this op actually names (should be exactly one)."""
    return [verb for verb in _PATCH_VERBS if getattr(op, verb) is not None]


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

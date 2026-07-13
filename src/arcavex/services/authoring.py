"""Template authoring service: scaffold, inspect, and split (spec §6.1.3).

These operations back ``arcavex template new/inspect/split``. They call the same compiler the
render path uses, so an inspected contract cannot drift from what actually compiles. The
service returns versioned kernel response models and never raises across the facade boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arcavex.kernel.api import (
    CompilerProtocol,
    FormatInfo,
    FunctionInfo,
    NodeInfo,
    ScaffoldResult,
    SplitResult,
    TemplateInspectReport,
    VariableInfo,
)
from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic, has_errors
from arcavex.kernel.ir.units import Dim
from arcavex.services.template.functions import FUNCTION_SIGNATURES
from arcavex.services.template.loader import (
    _SIDECARS,
    dump_yaml,
    line_of,
    load_template,
    load_yaml,
    resolve_template_path,
)

# The sections a one-file template splits into, mapped to their sidecar filename. Mirrors the
# loader's merge so a split template loads back to identical content.
_SPLIT_MAP: tuple[tuple[str, str], ...] = (
    ("variables", "schema.yaml"),
    ("formats", "formats.yaml"),
    ("locales", "locales.yaml"),
    ("preview_data", "preview-data.yaml"),
)

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
            nodes=nodes,
            functions=_function_infos(self._functions),
            preview_data=preview_data if isinstance(preview_data, dict) else {},
            diagnostics=diagnostics,
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


def _function_infos(names: list[str]) -> list[FunctionInfo]:
    """Build inspect's function list with a signature and one-line doc for each name (DX-3)."""
    out: list[FunctionInfo] = []
    for name in sorted(names):
        signature, doc = FUNCTION_SIGNATURES.get(name, (f"{name}(…)", None))
        out.append(FunctionInfo(name=name, signature=signature, doc=doc))
    return out


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


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

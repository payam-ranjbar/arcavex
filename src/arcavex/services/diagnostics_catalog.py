"""Canonical catalog of diagnostic-code documentation entries.

This module is the single source of truth for ``arcavex explain`` (spec §3.7 / §6.1.3, item
6). A Python catalog was chosen over loose files as the canonical form because it is trivially
wheel-safe (no ``importlib.resources`` path juggling) and mypy-checked. The human-browsable
``docs/diagnostics/<code>.md`` files are generated from this catalog and a test keeps them in
sync (``tests/unit/test_explain.py``), so the two never drift. A separate coverage test asserts
every code the engine can emit has an entry here.

Each entry is one concise paragraph describing the cause plus a typical fix.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticDoc:
    """One diagnostic-code documentation entry."""

    code: str
    title: str
    summary: str
    fix: str


def _e(code: str, title: str, summary: str, fix: str) -> tuple[str, DiagnosticDoc]:
    return code, DiagnosticDoc(code=code, title=title, summary=summary, fix=fix)


CATALOG: dict[str, DiagnosticDoc] = dict(
    [
        _e(
            "ARC-TPL-001",
            "Template file or directory not found",
            "The template path does not exist, or a directory template has no template.yaml.",
            "Check the path on the command line; a split template directory needs a "
            "template.yaml file.",
        ),
        _e(
            "ARC-TPL-002",
            "Invalid YAML syntax",
            "The template or data file is not valid YAML at the reported location.",
            "Fix the YAML syntax error (indentation, quoting, or a stray character) at that "
            "line.",
        ),
        _e(
            "ARC-TPL-003",
            "Template root is not a mapping",
            "A template file must be a YAML mapping with sections such as 'root:' and "
            "'formats:'.",
            "Make the top level a mapping, not a list or scalar.",
        ),
        _e(
            "ARC-TPL-004",
            "Template has no root node",
            "The template does not define a 'root:' node describing the scene.",
            "Add a 'root:' group node with children.",
        ),
        _e(
            "ARC-TPL-005",
            "Root node is not a group",
            "The root node must be of type 'group'.",
            "Set 'type: group' on the root node.",
        ),
        _e(
            "ARC-TPL-012",
            "Data file root is not a mapping",
            "The data file must be a mapping of variable names to values, not a list or "
            "scalar.",
            "Write the data file as 'name: value' pairs.",
        ),
        _e(
            "ARC-TPL-013",
            "'variables' is not a mapping",
            "The 'variables' section (or schema.yaml) must be a mapping of names to "
            "declarations.",
            "Write 'variables:' as e.g. 'title: {type: string, required: true}'.",
        ),
        _e(
            "ARC-TPL-014",
            "Required or referenced variable is missing",
            "A variable is required but not provided, or an expression references a variable "
            "that is neither declared nor supplied.",
            "Add the value to your data file, give the variable a default, or guard the "
            "reference with '| default(...)'.",
        ),
        _e(
            "ARC-TPL-015",
            "Variable type mismatch",
            "A supplied or default value does not match its declared type.",
            "Provide a value of the declared type, or change the declared type.",
        ),
        _e(
            "ARC-TPL-016",
            "Unknown variable type",
            "A variable declares a 'type' that is not one of the supported types.",
            "Use one of: string, number, boolean, color, image, list, object.",
        ),
        _e(
            "ARC-TPL-017",
            "Value not in enum",
            "A supplied or default value is not one of the values listed in the variable's "
            "'enum'.",
            "Use one of the allowed enum values, or widen the enum.",
        ),
        _e(
            "ARC-TPL-018",
            "Number coerced to string",
            "A number was supplied for a variable declared as a string; it was stringified "
            "with a warning.",
            "Quote the value in your data to make the string intent explicit, or declare the "
            "variable as a number.",
        ),
        _e(
            "ARC-TPL-020",
            "No formats declared",
            "The template has no 'formats:' section, so there is no canvas to render.",
            "Add a 'formats:' section with at least one named canvas.",
        ),
        _e(
            "ARC-TPL-021",
            "Format is ambiguous",
            "No format was specified and the template defines more than one.",
            "Pass --format with one of the declared format names.",
        ),
        _e(
            "ARC-TPL-022",
            "Unknown format",
            "The requested format is not declared by the template.",
            "Use one of the template's declared format names.",
        ),
        _e(
            "ARC-TPL-023",
            "Format has no canvas",
            "A format entry does not define a 'canvas' with width, height, and dpi.",
            "Give the format a 'canvas: {width, height, dpi}'.",
        ),
        _e(
            "ARC-TPL-030",
            "Node has no id",
            "Every node requires a stable, human-readable 'id'.",
            "Add a unique 'id:' to the node.",
        ),
        _e(
            "ARC-TPL-031",
            "Unknown node type",
            "A node declares a 'type' that is not a supported node kind.",
            "Use one of: group, text, image, shape, path.",
        ),
        _e(
            "ARC-TPL-032",
            "Group children are malformed",
            "A group's 'children' must be a list of node mappings or repeat/if constructs.",
            "Provide 'children:' as a YAML list.",
        ),
        _e(
            "ARC-TPL-033",
            "Invalid group direction",
            "A group's 'direction' must be 'ltr' or 'rtl'.",
            "Use 'direction: ltr' or 'direction: rtl'.",
        ),
        _e(
            "ARC-TPL-034",
            "Image node has no asset",
            "An image node requires an 'asset' path.",
            "Set 'asset:' to a template-relative image path.",
        ),
        _e(
            "ARC-TPL-035",
            "Invalid image fit",
            "An image node's 'fit' must be one of the supported fit modes.",
            "Use 'fill', 'contain', or 'cover'.",
        ),
        _e(
            "ARC-TPL-036",
            "Unsupported shape",
            "A shape node uses a shape kind not supported in this build.",
            "Use 'rect', 'rrect', or 'circle'.",
        ),
        _e(
            "ARC-TPL-037",
            "Invalid text align",
            "A text node's 'align' is not a supported value.",
            "Use left, right, center, start, or end.",
        ),
        _e(
            "ARC-TPL-038",
            "Invalid text direction",
            "A text node's 'direction' must be 'ltr' or 'rtl'.",
            "Use 'direction: ltr' or 'direction: rtl'.",
        ),
        _e(
            "ARC-TPL-052",
            "Stacks not supported yet",
            "Stack layouts (hstack/vstack) are not available in this build.",
            "Use anchor constraints; stacks arrive in Phase 2.",
        ),
        _e(
            "ARC-TPL-053",
            "line_height not supported",
            "The bundled text stack cannot honor a custom line height in this build.",
            "Remove 'line_height'; it arrives when the text stack gains strut support.",
        ),
        _e(
            "ARC-TPL-054",
            "repeat missing 'as'",
            "A repeat construct requires an 'as' name for its loop variable.",
            "Add 'as: item' so the repeated node can reference each element.",
        ),
        _e(
            "ARC-TPL-055",
            "repeat missing 'key'",
            "A repeat construct requires a stable 'key' expression for stable expanded IDs.",
            "Add 'key: \"{{ item.id }}\"' (or '{{ loop.index }}' if order is stable).",
        ),
        _e(
            "ARC-TPL-056",
            "repeat target is not a list",
            "A repeat's expression did not evaluate to a list.",
            "Iterate over a list-valued variable.",
        ),
        _e(
            "ARC-TPL-057",
            "repeat key derived from index",
            "A repeat key is derived from loop.index, so reordering the data changes node IDs.",
            "Prefer a stable field such as '{{ item.id }}' when the data has one.",
        ),
        _e(
            "ARC-TPL-058",
            "Duplicate repeat key",
            "Two iterations of a repeat produced the same key, which would collide expanded "
            "IDs.",
            "Make the key expression unique per item.",
        ),
        _e(
            "ARC-TPL-059",
            "Construct missing 'node'",
            "A repeat/if construct requires a single 'node' mapping to expand.",
            "Give the construct a 'node:' body.",
        ),
        _e(
            "ARC-TPL-060",
            "Invalid expression",
            "A '{{ … }}' expression has a syntax error or an invalid operation.",
            "Check the expression syntax and the functions it calls.",
        ),
        _e(
            "ARC-TPL-061",
            "repeat and if on the same node",
            "A single child declares both a 'repeat' and an 'if'. Applying both to one entry "
            "is ambiguous — whether the condition gates each iteration or the whole loop — so "
            "rather than silently pick one, the compiler asks you to nest them explicitly.",
            "Nest the constructs: make the 'if' construct the repeat's 'node' (the condition "
            "then gates each item), or put the 'repeat' construct inside the if's 'node' (the "
            "condition gates the whole loop).",
        ),
        _e(
            "ARC-TPL-062",
            "Expression budget exceeded",
            "An expression exceeded its evaluation step/time/token budget.",
            "Simplify the expression so it stays within the budget.",
        ),
        _e(
            "ARC-TPL-063",
            "repeat iteration cap exceeded",
            "A repeat would produce more than the allowed number of items.",
            "Reduce the collection to at most 1000 items.",
        ),
        _e(
            "ARC-TPL-070",
            "Scaffold target already exists",
            "'template new' refuses to write into a directory that already exists and contains "
            "files, so it can never overwrite work you already have. A path that does not yet "
            "exist, or an empty directory, is accepted.",
            "Point 'template new' at a new or empty directory, or move the existing contents "
            "aside first. To evolve a template you already have, edit it directly rather than "
            "re-scaffolding over it.",
        ),
        _e(
            "ARC-TPL-071",
            "Template is already split",
            "'template split' moves the inline variables/formats/locales/preview_data sections "
            "of a one-file template into sidecar files. It refuses when a sidecar already "
            "exists, because the template is already in directory form and re-splitting would "
            "have nothing to move or could clobber a sidecar.",
            "Edit the existing sidecar files directly — there is no reverse 'join' command. If "
            "you deliberately merged sections back inline and want to re-split, delete the "
            "leftover sidecar files first.",
        ),
        _e(
            "ARC-TPL-090",
            "Style packs not supported yet",
            "Opting into a style pack is not available in this build.",
            "Remove the style option; style packs arrive in Phase 3.",
        ),
        _e(
            "ARC-TPL-091",
            "Locale application not supported yet",
            "Applying a requested locale (direction, digit policy, overlays) is Phase 2.",
            "Drop --locale for now; locale files are still parsed for shape.",
        ),
        _e(
            "ARC-TPL-093",
            "Inline styles not supported yet",
            "A template-level 'styles' section is not available in this build.",
            "Remove the 'styles' section; style packs arrive in Phase 3.",
        ),
        _e(
            "ARC-TPL-094",
            "Style opt-in not supported yet",
            "A template-level 'style' opt-in is not available in this build.",
            "Remove the 'style' key; style packs arrive in Phase 3.",
        ),
        _e(
            "ARC-TPL-095",
            "Format patch not supported yet",
            "Per-format 'patch' operations are not available in this build.",
            "Remove the format patch; format patches arrive in Phase 2.",
        ),
        _e(
            "ARC-TPL-096",
            "styles.yaml sidecar not supported yet",
            "A 'styles.yaml' split sidecar is not available in this build.",
            "Remove styles.yaml; style packs arrive in Phase 3.",
        ),
        _e(
            "ARC-TPL-097",
            "Section defined twice",
            "A section (variables, formats, locales, or preview_data) is defined both inline "
            "in template.yaml and in its split sidecar file. Arcavex will not guess which wins "
            "— silent precedence between two definitions is exactly the ambiguity the split "
            "format exists to avoid.",
            "Keep each section in exactly one place. Delete the inline section from "
            "template.yaml, or delete the sidecar file, so the section has a single definition.",
        ),
        _e(
            "ARC-TPL-098",
            "Malformed locales section",
            "The 'locales' section is not a mapping of locale names to setting mappings.",
            "Write 'locales:' as e.g. 'fa: {direction: rtl}'.",
        ),
        _e(
            "ARC-TPL-099",
            "Invalid locale setting",
            "A locale entry has an unknown setting key or an out-of-range value. Locale files "
            "are validated for shape now even though locale application is Phase 2, so mistakes "
            "surface while you author. Direction must be 'ltr' or 'rtl'; digits must be one of "
            "'en', 'fa', 'latn', 'arab'; fonts and data must be mappings and patch a list.",
            "Correct the flagged key or value. The known per-locale settings are direction, "
            "digits, fonts, data, and patch.",
        ),
        _e(
            "ARC-IR-010",
            "Missing dimension",
            "A dimension value is missing where one is required.",
            "Provide a value such as '40pt', '210mm', or '1080px'.",
        ),
        _e(
            "ARC-IR-011",
            "Invalid dimension",
            "A dimension value could not be parsed.",
            "Use a number with an optional unit: px, pt, mm, or %.",
        ),
        _e(
            "ARC-IR-012",
            "Invalid percent size",
            "A percentage size value is malformed.",
            "Use a value like '62%'.",
        ),
        _e(
            "ARC-IR-013",
            "Canvas dpi must be positive",
            "The canvas 'dpi' is zero or negative.",
            "Use a positive integer such as 96 or 300.",
        ),
        _e(
            "ARC-IR-014",
            "Value is not a number",
            "A field that must be numeric received a non-numeric value.",
            "Provide a numeric value.",
        ),
        _e(
            "ARC-IR-020",
            "Duplicate node id",
            "Two nodes share the same id, which must be unique across the template.",
            "Rename one of the nodes so every id is unique.",
        ),
        _e(
            "ARC-IR-030",
            "Invalid color",
            "A color value could not be parsed.",
            "Use #hex, rgb()/rgba(), or a named color.",
        ),
        _e(
            "ARC-LAY-010",
            "Unknown anchor key",
            "A node uses an anchor key that is not a recognized edge.",
            "Anchor keys are top, bottom, left, right, center_x, center_y.",
        ),
        _e(
            "ARC-LAY-011",
            "Anchor must reference a parent edge",
            "An anchor value does not reference a parent edge.",
            "Write anchors like 'parent.top' or 'parent.left+20pt'.",
        ),
        _e(
            "ARC-LAY-012",
            "Invalid anchor offset",
            "An anchor offset could not be parsed into a fixed distance. The most common cause "
            "is a '{{ … }}' expression inside a constraint (e.g. 'parent.left + {{ i*240 }}px'): "
            "constraint values are static in this build — the evaluator does not run inside "
            "anchors, sizes, or offsets, so the braces are read as literal text and fail to "
            "parse. A malformed unit (missing number or unknown suffix) triggers it too.",
            "Use a literal offset such as '+20px', '+20pt', or '-6mm'. Computed or per-item "
            "offsets are not available until layout stacks arrive in Phase 2; until then give "
            "each node a distinct literal anchor.",
        ),
        _e(
            "ARC-LAY-013",
            "Unknown parent edge",
            "An anchor references a parent edge that does not exist.",
            "Parent edges are top, bottom, left, right, center_x, center_y.",
        ),
        _e(
            "ARC-LAY-014",
            "Unsupported anchor edge",
            "The layout solver received an anchor edge it does not support in this build.",
            "Use one of the six physical parent edges.",
        ),
        _e(
            "ARC-LAY-040",
            "Repeated siblings overlap",
            "A 'repeat' expanded more than one sibling node, and because constraint values are "
            "static in this build (no expressions inside constraints, no layout stacks yet) "
            "every expanded sibling inherits the same anchors and size — so they resolve to "
            "identical bounds and stack on top of one another. This is a warning, not an "
            "error: the render still succeeds.",
            "Give each repeated item a distinct literal anchor when the count is fixed, or wait "
            "for layout stacks (Phase 2), which position repeated children automatically.",
        ),
        _e(
            "ARC-LAY-020",
            "fit_content on a non-text node",
            "Only text nodes support the 'fit_content' size mode in this build.",
            "Give the node an explicit size, or make it a text node.",
        ),
        _e(
            "ARC-LAY-030",
            "Node under-constrained",
            "A node does not resolve exactly one position on an axis.",
            "Add exactly one anchor per axis (horizontal and vertical).",
        ),
        _e(
            "ARC-LAY-031",
            "Node over-constrained",
            "A node resolves more than one position on an axis.",
            "Keep exactly one anchor per axis; size comes from the size spec.",
        ),
        _e(
            "ARC-LAY-032",
            "Node missing a size",
            "A node has constraints but no complete size for one or both axes.",
            "Add 'size: {w: ..., h: ...}' (fixed, %, fill, or fit_content).",
        ),
        _e(
            "ARC-RND-010",
            "Font family not bundled",
            "A text node requests a font family that is not in the bundled font database.",
            "Use one of the available families, or add the font under library-seed/fonts.",
        ),
        _e(
            "ARC-RND-900",
            "Masks not supported yet",
            "Mask declarations are not available in this build.",
            "Remove the 'mask'; masks arrive in Phase 2.",
        ),
        _e(
            "ARC-RND-901",
            "Rotation/scale not supported yet",
            "Rotation and scale transforms are not available in this build.",
            "Use only translation transforms for now.",
        ),
        _e(
            "ARC-FX-900",
            "Effects not supported yet",
            "Effect declarations are not available in this build.",
            "Remove the 'effects'; effects arrive in Phase 3.",
        ),
        _e(
            "ARC-AST-001",
            "Image asset not found",
            "An image node references a file that does not exist relative to the template.",
            "Check the path is relative to the template file and that the file exists.",
        ),
        _e(
            "ARC-AST-002",
            "Image asset could not be decoded",
            "An image file exists but could not be decoded as a supported image.",
            "Check the file is a supported, undamaged image format.",
        ),
        _e(
            "ARC-EXP-001",
            "Export failed",
            "Writing the rendered surface to the output file failed.",
            "Check the output path is writable and the disk has space.",
        ),
        _e(
            "ARC-EXP-011",
            "Unsupported output extension",
            "The requested output file extension is not a supported export format.",
            "Use a '.png' output path in this build.",
        ),
        _e(
            "ARC-EXT-001",
            "Duplicate component name",
            "Two components register the same name for one contract kind.",
            "Component names are globally unique per kind; rename one provider.",
        ),
        _e(
            "ARC-EXT-002",
            "Component not registered",
            "A named component was requested but is not registered.",
            "Check the component name against the available components.",
        ),
        _e(
            "ARC-INT-999",
            "Internal engine error",
            "An unexpected internal error occurred and was wrapped rather than crashing.",
            "This is a bug; please report it with the input that triggered it.",
        ),
    ]
)


def documented_codes() -> set[str]:
    """Return the set of codes with a documentation entry."""
    return set(CATALOG)


def render_markdown(doc: DiagnosticDoc) -> str:
    """Render one catalog entry to its canonical ``docs/diagnostics/<code>.md`` form.

    This is the single formatter shared by the docs generator and the mirror test, so the
    Markdown files can never drift from the catalog.
    """
    return (
        f"# {doc.code} — {doc.title}\n\n"
        f"{doc.summary}\n\n"
        f"**Typical fix:** {doc.fix}\n"
    )


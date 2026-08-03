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
            "ARC-TPL-039",
            "Invalid stack setting",
            "A group's stack layout has an invalid value: 'layout' must be absolute/hstack/"
            "vstack, 'main_align' must be start/center/end/space_between, and 'cross_align' "
            "must be start/center/end/stretch.",
            "Correct the flagged stack setting to one of its allowed values.",
        ),
        _e(
            "ARC-TPL-040",
            "Malformed text runs",
            "A text node's 'runs' is not a list, or a run entry is neither a string nor a "
            "{text, ...} mapping.",
            "Write 'runs:' as a list of strings or mappings, each with a 'text' field.",
        ),
        _e(
            "ARC-TPL-041",
            "Invalid text fit policy",
            "A text node's 'fit' block has an invalid value: 'policy' must be wrap/shrink_to_fit/"
            "truncate and 'overflow' must be clip/allow/error.",
            "Correct the fit policy or overflow value; add 'min_size' for shrink_to_fit.",
        ),
        _e(
            "ARC-TPL-051",
            "Unknown field in a node sub-block",
            "A node sub-block — style, paragraph, fit, constraints, size, run, transform, "
            "mask, padding, or a repeat/if construct — contains a field name the compiler does "
            "not recognize (often a typo such as 'font_wieght'). Unknown fields are rejected "
            "rather than silently ignored, so a misspelled property cannot quietly do nothing. "
            "The node top level and the template-level scopes carry their own codes: "
            "ARC-TPL-064 (node), ARC-TPL-065 (template root), ARC-TPL-066 (format/canvas), "
            "ARC-TPL-067 (variable declaration), and ARC-TPL-068 (effect entry).",
            "Fix the field name; the diagnostic lists the valid fields for that block.",
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
            "rather than silently pick one, the compiler asks you to nest them explicitly. A "
            "construct's 'node' is built directly (it is not itself scanned for nested "
            "constructs), so the inner construct must live inside a group's 'children' list.",
            "Nest through a wrapper group: make the repeat's 'node' a group whose 'children' "
            "list holds the 'if' construct (the condition gates each item), or make the if's "
            "'node' a group whose 'children' list holds the 'repeat' construct (the condition "
            "gates the whole loop).",
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
            "ARC-TPL-064",
            "Unknown node field",
            "A node's top level carries a field the compiler never reads. This is the scope "
            "where an invented field is most damaging: it validates clean, does nothing, and "
            "the author keeps building on the belief that it works. Arcavex has no per-node "
            "'condition' (gate a node with the structural 'if:' / 'node:' construct), no "
            "node-level paint fields (they live in 'style:'), and no node-level geometry "
            "fields (they live in 'constraints:' and 'transform:').",
            "Read the hint: it names where a wrong-scope field actually belongs, or which node "
            "kind owns it, and otherwise lists the valid fields for this node's kind.",
        ),
        _e(
            "ARC-TPL-065",
            "Unknown template root field",
            "The template's top level declares a section the engine does not read. Only "
            "'version', 'variables', 'formats', 'locales', 'preview_data', 'style', 'root', "
            "and 'seed' are template sections; anything else would be silently ignored.",
            "Remove the section or correct its name; the diagnostic lists the valid ones.",
        ),
        _e(
            "ARC-TPL-066",
            "Unknown format or canvas field",
            "A 'formats.<name>' entry, or its 'canvas' block, carries a field the engine does "
            "not read. A format holds only 'canvas' and an optional 'patch'; a canvas holds "
            "'width', 'height', 'dpi', and an optional 'bleed'. Every declared format is "
            "checked, not only the one being rendered.",
            "Correct the field name; a canvas size belongs in 'width'/'height' and a per-format "
            "override belongs in 'patch'.",
        ),
        _e(
            "ARC-TPL-067",
            "Unknown variable-declaration field",
            "A 'variables.<name>' declaration carries a field the engine does not read. A "
            "declaration holds 'type', 'required', 'default', 'enum', and 'doc'.",
            "Correct the field name; describe the variable with 'doc' and constrain it with "
            "'type'/'enum'.",
        ),
        _e(
            "ARC-TPL-068",
            "Unknown effect-entry field",
            "An entry in a node's 'effects:' list carries a field the engine does not read. An "
            "entry is a bare effect name, an inline '{name, params}', or a '{preset: name}' "
            "reference into the style pack's effect presets.",
            "Put per-effect settings inside 'params:', and reference a style-pack preset with "
            "'preset:'.",
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
            "ARC-TPL-092",
            "Invalid patch operation",
            "A format or locale patch is malformed: an op is not a mapping, does not have "
            "exactly one of set/remove/insert_before/insert_after, addresses a path that is not "
            "'nodes.<id>[.<field>...]', targets a node id or field that does not exist, or an "
            "insert has no 'node' body.",
            "Fix the patch op: address an existing authored node id, use one verb per op, and "
            "give inserts a 'node:' mapping.",
        ),
        _e(
            "ARC-TPL-110",
            "Template changed on disk",
            "A 'patch_template' call passed a base hash that no longer matches the template file "
            "on disk, so another writer changed the file since it was read. The patch is refused "
            "before anything is written, so a concurrent edit is never silently overwritten.",
            "Re-inspect the template to get its current content hash, rebase the edit on the "
            "current file, and retry the patch.",
        ),
        _e(
            "ARC-TPL-111",
            "Invalid data keypath",
            "A 'set_data' keypath is empty, or one of its dotted segments descends into a value "
            "that is not a mapping (for example addressing 'contact.email' when 'contact' is "
            "already a scalar string). Only mappings can be traversed.",
            "Use a dotted keypath whose intermediate segments are mappings; clear the offending "
            "scalar first, or choose a different path.",
        ),
        _e(
            "ARC-TPL-112",
            "Data key matches no declared variable",
            "A 'set_data' or 'import_data' top-level key does not correspond to any variable the "
            "template declares, so the value is written but no template expression ever reads it "
            "— usually a typo (for example 'titel' for 'title'). This is a warning, not an error, "
            "because deliberately-extra data can be legitimate.",
            "Check the key against the template's declared variables (from 'template inspect'); "
            "fix the name, or ignore the warning if the extra data is intentional.",
        ),
        _e(
            "ARC-TPL-100",
            "Undeclared locale",
            "A locale was requested with --locale that the template does not declare, so its "
            "direction, digits, fonts, data, and patch are unknown. Arcavex never silently "
            "ignores a requested locale.",
            "Declare the locale under 'locales:' in the template, or request one the template "
            "already defines.",
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
            "A dimension value could not be parsed. In a size axis, a bare value must be a "
            "number with a unit (px/pt/mm), a percentage, or one of the size keywords 'fill', "
            "'fit_content', and 'aspect(W:H)'.",
            "Use a number with a unit (e.g. '40pt', '210mm', '1080px'), a percentage, or a "
            "size keyword ('fill', 'fit_content', 'aspect(3:4)').",
        ),
        _e(
            "ARC-IR-012",
            "Invalid size value",
            "A size mapping is malformed: a percentage that will not parse, an 'aspect' ratio "
            "that is not 'W:H' with positive numbers, or a size mapping missing its 'value'/"
            "'aspect' key.",
            "Use a value like '62%', an aspect like {aspect: '3:4'} (or 'aspect(3:4)'), or give "
            "the mapping a 'value:'.",
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
            "ARC-IR-040",
            "Malformed mask declaration",
            "A node's 'mask' is not a mapping, is missing its 'component' name, or its 'params' "
            "is not a mapping.",
            "Write 'mask: {component: diamond_grid, params: {cell: 90pt, gutter: 6pt}}'.",
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
            "An anchor offset could not be parsed into a fixed distance, usually a malformed "
            "unit (missing number or unknown suffix). '{{ }}' expressions ARE evaluated inside "
            "constraint strings before the offset is parsed, so a leftover brace means a "
            "malformed or nested expression rather than an unsupported feature.",
            "Use an offset such as '+20px', '+20pt', or '-6mm'. Per-item offsets from "
            "expressions work — e.g. 'top: parent.top+{{ loop.index * 90 }}pt' — as long as the "
            "expression resolves to a numeric distance.",
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
            "A 'repeat' expanded more than one sibling node in an *absolute* group, and every "
            "expanded sibling carries the same fixed anchors and size — so they resolve to "
            "identical bounds and stack on top of one another. This is a warning, not an error: "
            "the render still succeeds. It does not fire inside a stack (the stack positions "
            "each child) nor when the anchors carry per-item expressions that separate them.",
            "Give each item a distinct anchor with a per-item offset (e.g. "
            "'top: parent.top+{{ loop.index * 90 }}pt'), or wrap the repeat in a "
            "'layout: vstack'/'hstack' group so the stack positions each child.",
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
            "Add 'size: {w: ..., h: ...}' — each of fixed (e.g. 100px), a %, 'fill', "
            "'fit_content', or {aspect: 'W:H'}.",
        ),
        _e(
            "ARC-LAY-050",
            "Text overflow configured as error",
            "A text node still overflows its resolved box after its fit policy ran, and the "
            "node's 'overflow' is set to 'error', so rendering fails rather than clipping or "
            "spilling. The message reports the shaped extent and the box extent.",
            "Enlarge the box, reduce the text or font size, lower min_size for shrink_to_fit, "
            "or set overflow to 'clip' or 'allow'.",
        ),
        _e(
            "ARC-LAY-051",
            "Text fit did not converge",
            "A 'shrink_to_fit' text node could not be made to fit even at its smallest allowed "
            "size within the ≤ 8 measurement iterations, so it still overflows. This is a "
            "warning: the text is clipped or allowed per the overflow policy and the render "
            "still succeeds.",
            "Lower min_size so a smaller, fitting size exists, enlarge the box, or switch the "
            "policy to 'truncate'. Note the direction: 'min_size' is the floor of the shrink "
            "search, so raising it removes the only candidates that could still fit and makes "
            "the overflow strictly worse.",
        ),
        _e(
            "ARC-LAY-052",
            "Sibling anchor cycle",
            "Two or more sibling nodes anchor to each other in a loop, so no resolution order "
            "exists. The message names the full cycle.",
            "Break the loop so at least one node in it anchors to the parent or to a node "
            "resolved before it.",
        ),
        _e(
            "ARC-LAY-053",
            "Unknown sibling anchor reference",
            "A node's anchor references a sibling id that does not exist in the same group.",
            "Anchor to an existing sibling id in the same group, or to 'parent'.",
        ),
        _e(
            "ARC-LAY-054",
            "Stack child has position anchors",
            "A child of an hstack/vstack group declares position anchors, but a stack positions "
            "its own children along the main axis, so anchors would contradict it.",
            "Remove the 'anchor' block from the stack child; use gap, padding, and the stack's "
            "alignment to position it. Size modes still apply.",
        ),
        _e(
            "ARC-LAY-055",
            "Invalid aspect size mode",
            "A node declares the 'aspect' size mode on both axes, or on one axis while the other "
            "axis cannot be resolved to a concrete value, so the derived dimension is undefined.",
            "Give exactly one axis a concrete size (fixed, %, or fill); 'aspect' derives the "
            "other axis from it.",
        ),
        _e(
            "ARC-LAY-056",
            "Wrapping stacks not supported yet",
            "A stack group set 'wrap: true', but wrapping (flowing children onto multiple rows "
            "or columns) is deferred in this build rather than faked.",
            "Lay wrapped rows out explicitly with nested stacks for now, or drop 'wrap'.",
        ),
        _e(
            "ARC-LAY-057",
            "Text still exceeds max_lines",
            "A text node wraps onto more lines than 'max_lines' allows while each line does fit "
            "the box width, and 'overflow' is 'error'. The binding constraint is the line cap, "
            "not the box, so this is reported separately from ARC-LAY-050: the message names the "
            "measured line count, the cap, and the size the text reached rather than a width x "
            "height pair, because the measured height is simply what that many lines occupy — it "
            "does not change when the box grows. Both fit policies that can hit the cap report "
            "it: 'shrink_to_fit' once it has bottomed out at its 'min_size' floor (while it is "
            "still shrinking the line count is not yet final), and 'wrap', which does no search "
            "at all, so the authored size is the size.",
            "Widen the box so the text needs fewer lines, or raise max_lines. Under "
            "'shrink_to_fit' also consider lowering min_size so it can shrink further; under "
            "'wrap' there is no floor to lower, so reduce the font size or switch to "
            "'shrink_to_fit' with a min_size. Enlarging the box height cannot help.",
        ),
        _e(
            "ARC-RND-010",
            "Font family not available",
            "A text node requests a font family the engine has not loaded. Rendering is confined "
            "to the bundled families plus any installed under the Arcavex home — system fonts are "
            "never consulted, because determinism requires it — so a typeface that is merely "
            "installed on the operating system will not resolve. The name must be the font's "
            "FAMILY (e.g. 'Lateef'), which often differs from its file name.",
            "Use one of the families the hint lists, or install the typeface with 'arcavex font "
            "add <path/to/font.ttf>', which reports the exact family name to write. 'arcavex "
            "font list' shows every available family and the install directory.",
        ),
        _e(
            "ARC-RND-011",
            "Missing glyph",
            "A text run contains a code point that no loaded font can render, so it would "
            "paint as a tofu box. Rendering is confined to the loaded fonts for determinism, so "
            "the shaper never falls back to a system font. This is a warning; the render "
            "proceeds.",
            "Install a font covering the reported code points with 'arcavex font add "
            "<path/to/font.ttf>', or remove the unsupported characters from the text.",
        ),
        _e(
            "ARC-RND-030",
            "Font file not found",
            "'arcavex font add' was given a path that does not exist or is not a file.",
            "Check the path; pass the .ttf file itself, not the directory containing it.",
        ),
        _e(
            "ARC-RND-031",
            "Font file is not a usable typeface",
            "'arcavex font add' was given a file the shaper cannot read as a TrueType font, "
            "either because of its extension or because Skia could not parse its contents. Such "
            "a file is refused rather than installed, since it would sit in the font directory "
            "providing no family and silently fail to resolve.",
            "Install a .ttf file the engine can read; re-download or re-export the font, "
            "converting from another format (.otf, .woff2) to TrueType first.",
        ),
        _e(
            "ARC-RND-032",
            "Cannot remove a bundled font family",
            "'arcavex font remove' named a family that ships with the engine. Bundled families "
            "back the default font stacks, so removing one would break templates that never "
            "opted into anything unusual, and the files would return on the next reinstall.",
            "Only families added with 'arcavex font add' can be removed; 'arcavex font list' "
            "marks which families are bundled and which are installed.",
        ),
        _e(
            "ARC-RND-033",
            "No such installed font family",
            "'arcavex font remove' named a family that is not installed. Names are case-"
            "sensitive and must be the font's family name, not the file name it was added from.",
            "Run 'arcavex font list' to see the installed family names, and pass one of those.",
        ),
        _e(
            "ARC-RND-034",
            "Font store could not be read or written",
            "The font directory under the Arcavex home could not be read, created, or modified — "
            "typically a permissions problem, or a file held open by another process.",
            "Check that the Arcavex home is readable and writable; 'arcavex doctor' reports "
            "which home directory is in effect.",
        ),
        _e(
            "ARC-RND-020",
            "Output dimension exceeds the render budget",
            "The render surface is wider or taller than the per-render output-dimension budget "
            "(spec §8.3). The limit is checked from the canvas size and DPI before any pixels are "
            "allocated, so an accidental runaway (a huge canvas, or a DPI override that multiplies "
            "it) is refused rather than exhausting memory.",
            "Reduce the format's canvas size or the render DPI, or raise "
            "[budgets].max_dimension in config.toml.",
        ),
        _e(
            "ARC-RND-021",
            "Render surface exceeds the pixel budget",
            "The render surface has more pixels than the per-render decoded-pixel budget allows "
            "(spec §8.3). Enforced from the canvas size and DPI before allocation, so a runaway "
            "surface cannot be created.",
            "Reduce the canvas size or the render DPI, or raise [budgets].max_pixels in "
            "config.toml.",
        ),
        _e(
            "ARC-RND-022",
            "Render surface exceeds the memory budget",
            "The render surface would need more bytes than the per-render surface-memory budget "
            "allows (spec §8.3). Enforced from the canvas size and DPI before allocation.",
            "Reduce the canvas size or the render DPI, or raise [budgets].max_surface_bytes in "
            "config.toml.",
        ),
        _e(
            "ARC-RND-023",
            "Render exceeded the wall-clock budget",
            "The render took longer than the per-render wall-clock budget (spec §8.3). This is a "
            "post-hoc guard — Skia renders are not preemptible in v1 — so it flags a pathological "
            "render after it completes rather than interrupting it.",
            "Simplify the scene or its effect chains, reduce the DPI, or raise "
            "[budgets].max_wall_ms in config.toml.",
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
            "Effect declaration rejected",
            "A legacy code retained for compatibility; effects now compile, so real effect "
            "problems report a more specific ARC-FX-9xx code.",
            "Check the specific effect diagnostic reported alongside this one, if any.",
        ),
        _e(
            "ARC-FX-901",
            "Unknown mask component",
            "A node references a mask component name that is not registered.",
            "Use a registered mask (e.g. rounded_rect, circle, diamond_grid), or add the mask "
            "as an extension.",
        ),
        _e(
            "ARC-FX-902",
            "Invalid mask or effect parameters",
            "A mask's or effect's parameters failed validation against the component's parameter "
            "schema (wrong name, type, or out-of-range value). Effect length params accept pt, "
            "mm, or px (px converts against the canvas DPI); mask length params are pt or mm.",
            "Check each parameter against the component's documented schema; the message lists "
            "every offending field so you can fix them in one pass.",
        ),
        _e(
            "ARC-FX-903",
            "Malformed effect list",
            "A node's 'effects' is not a list, or an entry is neither a name, a "
            "'{name, params}' mapping, nor a '{preset: name}' reference.",
            "Write 'effects:' as a list where each item is a name, '{name, params}', or "
            "'{preset: name}'.",
        ),
        _e(
            "ARC-FX-910",
            "Unknown effect",
            "A node references an effect name that is not registered.",
            "Use a registered effect (the message lists them), or add it as an extension.",
        ),
        _e(
            "ARC-FX-911",
            "Geometry effect on an unsupported node",
            "A geometry effect (e.g. torn-paper) rewrites a node's path, so it applies only to "
            "'shape' and 'path' nodes; it was placed on a text, image, or group node.",
            "Move the geometry effect onto a shape or path node, or remove it.",
        ),
        _e(
            "ARC-FX-912",
            "Invalid shape-generator parameters",
            "A shape generator's parameters failed validation against its schema, or the "
            "generator raised while building its path.",
            "Check each parameter against the generator's documented schema; the message lists "
            "every offending field so you can fix them in one pass.",
        ),
        _e(
            "ARC-FX-913",
            "Unknown shape generator",
            "A shape node references a generator name that is not registered.",
            "Use a registered generator (starburst, speech_bubble, qr_code), or add it as an "
            "extension.",
        ),
        _e(
            "ARC-STY-001",
            "Unknown or missing style pack",
            "The template's 'style:' reference names a library pack that is not installed, a "
            "version that does not exist, or a local file that is missing.",
            "Use 'style: name@version' matching an installed pack, or a './file.yaml' path "
            "relative to the template; the message lists what is available.",
        ),
        _e(
            "ARC-STY-002",
            "Invalid style pack",
            "A style pack file is not a mapping, or contains keys outside the supported set "
            "(version, palettes, fonts, effect_presets, shape_presets, roles).",
            "Fix the pack so it is a YAML mapping using only the supported top-level keys.",
        ),
        _e(
            "ARC-STY-010",
            "Unknown effect preset",
            "A node references an effect preset that the active style pack does not define, or "
            "references a preset without opting into a style.",
            "Add 'style:' to the template and use a preset the pack defines; the message lists "
            "the available presets.",
        ),
        _e(
            "ARC-STY-011",
            "Unknown style role",
            "A node's 'style_role' names a role the active style pack does not define, or is "
            "used without opting into a style.",
            "Add 'style:' to the template and use a role the pack defines (e.g. heading, body, "
            "accent); the message lists the available roles.",
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
            "ARC-AST-003",
            "Image asset exceeds a decode guard",
            "An image is larger than a decode guard allows — too many source bytes, too many "
            "decoded pixels, or a disallowed format. The guard is enforced against the image "
            "header before any decompression, so a decompression bomb never gets decoded.",
            "Reduce the image's dimensions or file size, or convert it to an allowed raster "
            "format (PNG, JPEG, GIF, BMP, or WEBP).",
        ),
        _e(
            "ARC-AST-004",
            "Image asset escapes the template directory",
            "An image node's resolved asset path points outside the template's own directory — via "
            "a '..' segment or a symlink that leads out of it. Template-relative files must stay "
            "within the template directory (spec §8.3); the check runs on the fully resolved path, "
            "so it also catches a symlink whose target is elsewhere.",
            "Move the asset inside the template directory and reference it with a relative path "
            "that does not climb above the template root.",
        ),
        _e(
            "ARC-EXP-001",
            "Export failed",
            "Writing the rendered surface to the output file failed.",
            "Check the output path is writable and the disk has space.",
        ),
        _e(
            "ARC-EXP-002",
            "Image encoding failed",
            "The rendered surface could not be encoded to the requested raster format (PNG, JPEG, "
            "or WebP). This is an internal encoder failure, not a bad option.",
            "Retry the render; if it persists, report it with the template and format. Check "
            "'arcavex doctor' confirms the Skia build supports the format.",
        ),
        _e(
            "ARC-EXP-003",
            "PDF export failed",
            "The rendered surface could not be embedded into a PDF — Skia's PDF backend could not "
            "encode the raster or create the document.",
            "Retry the render; if it persists, report it. Check 'arcavex doctor' confirms Skia's "
            "PDF backend is available.",
        ),
        _e(
            "ARC-EXP-011",
            "Unsupported output extension",
            "The requested output file extension is not a supported export format. Arcavex selects "
            "the exporter from the output extension.",
            "Use one of the supported output extensions: .png, .jpg, .jpeg, .webp, or .pdf.",
        ),
        _e(
            "ARC-PRJ-001",
            "No project found",
            "No project.yaml was found in the current directory or any parent, and no valid "
            "--project path was given, so there is no project to act on.",
            "Run inside a project directory, pass --project <dir>, or create one with "
            "'arcavex project new'.",
        ),
        _e(
            "ARC-PRJ-002",
            "Invalid project manifest",
            "A project.yaml is missing a required field (at least 'name' and 'template'), is "
            "not a mapping, declares no formats to render, or its override file is not a list of "
            "patch operations.",
            "Fix project.yaml so it has 'name', 'template', and a 'formats:' list; write "
            "overrides as a YAML list of set/remove/insert ops.",
        ),
        _e(
            "ARC-PRJ-003",
            "Project target is not empty",
            "'project new' or 'project clone' refuses to write into a directory that already "
            "contains files, so it can never overwrite existing work.",
            "Choose a new or empty directory, or move the existing contents aside first.",
        ),
        _e(
            "ARC-PRJ-004",
            "Unknown project status",
            "A status was set that is not one of the tracked lifecycle states.",
            "Use one of: draft, review, approved, published.",
        ),
        _e(
            "ARC-PRJ-006",
            "Template upgrade or detach unavailable",
            "The operation needs a library-pinned template. The project's template is a local "
            "path (or is already detached), so version upgrades do not apply, or a detach target "
            "already exists.",
            "Pin the project to a library 'name@version' to enable upgrades, or remove an "
            "existing detached copy before detaching again.",
        ),
        _e(
            "ARC-PRJ-007",
            "Template detached from the library",
            "'template detach' copied a library template into the project. The project now "
            "references its own editable copy, so automatic version upgrades are no longer "
            "available for it (spec §5.4).",
            "Edit the copied template directly. Re-pin the project to a library 'name@version' "
            "if you want upgrades back.",
        ),
        _e(
            "ARC-LIB-001",
            "Unknown library template or version",
            "A template reference names a template that is not published, or a version that "
            "does not exist under it.",
            "Publish the template first, or reference an existing 'name@version'; the message "
            "lists what is available.",
        ),
        _e(
            "ARC-LIB-002",
            "Library version already published",
            "'template publish' refuses to overwrite an existing version directory, because "
            "published versions are immutable — a change is always a new version (spec §5.5).",
            "Publish under a new version number instead of reusing an existing one.",
        ),
        _e(
            "ARC-LIB-003",
            "Ambiguous bare template name",
            "A bare template name was used but the library declares no default version for it, "
            "so Arcavex will not silently pick 'latest' for a recorded render (spec §5.1).",
            "Reference an explicit 'name@version', or set a default alias for the template.",
        ),
        _e(
            "ARC-LIB-004",
            "Invalid library version or index",
            "A version string is malformed, or a template's index.toml is not valid TOML.",
            "Use a dotted version such as '1.0.0'; indexes are disposable, so a bad index can "
            "be deleted and regenerated by republishing.",
        ),
        _e(
            "ARC-RUN-001",
            "Run directory or manifest not found",
            "A run directory has no manifest.json, or the manifest could not be parsed against "
            "the current schema.",
            "Point at a run directory produced by a recorded render "
            "(outputs/<timestamp>_<hash>/) with an intact manifest.json.",
        ),
        _e(
            "ARC-RUN-002",
            "Recorded input changed on disk",
            "A rerun on the same engine and platform did not reproduce the original bytes "
            "because a recorded input changed on disk since the run was recorded — the template, "
            "the project override patch, the style pack, a referenced asset, or the bundled font "
            "environment. The rerun renders from the current on-disk inputs and names which one "
            "drifted, rather than only reporting that the outputs differ. This is a warning: the "
            "render still succeeds.",
            "Restore the named input to its recorded state to reproduce the original bytes, or "
            "accept the new render as the current truth. The run's reproduction.json lists the "
            "drifted inputs under 'input_drift'.",
        ),
        _e(
            "ARC-EXT-001",
            "Duplicate component name",
            "Two components claim the same name for one contract kind — an extension component "
            "shadowing a built-in or another added extension. Caught at 'ext validate' and 'ext "
            "add' (and again by the loader at start), naming both providers: the incumbent as a "
            "built-in or by its extension name, and the newcomer by its extension and class.",
            "Component names are globally unique per kind; rename the extension's component (and "
            "its manifest name) to one that is not already registered.",
        ),
        _e(
            "ARC-EXT-002",
            "Component not registered",
            "A named component was requested but is not registered.",
            "Check the component name against the available components.",
        ),
        _e(
            "ARC-EXT-010",
            "Extension manifest not found",
            "An extension directory has no extension.toml, so there is no manifest to load.",
            "Point at a directory containing an extension.toml, or scaffold one with "
            "'arcavex ext scaffold'.",
        ),
        _e(
            "ARC-EXT-011",
            "Invalid extension manifest",
            "The extension.toml is not valid TOML, a field has the wrong type, or a name/entry is "
            "not a valid identifier ('module:Class').",
            "Fix the flagged field; the manifest needs name, version, ir_min, engine_min, and a "
            "list of [[components]] tables with a valid kind, name, and 'module:Class' entry.",
        ),
        _e(
            "ARC-EXT-012",
            "Extension manifest missing a required field",
            "A required manifest field (name, version, ir_min, engine_min, a component field, or "
            "the component list) is absent.",
            "Add the missing field; every extension declares its identity, version floors, and at "
            "least one component.",
        ),
        _e(
            "ARC-EXT-013",
            "Unknown component kind",
            "A component (or 'ext scaffold') names a kind that is not one of the eight extensible "
            "contracts.",
            "Use one of: effect, mask, shape, exporter, layout_solver, template_function, "
            "backend, decoder.",
        ),
        _e(
            "ARC-EXT-014",
            "Duplicate component in manifest",
            "Two components in the same manifest declare the same kind and name.",
            "Component names are unique per kind; rename one of the two.",
        ),
        _e(
            "ARC-EXT-020",
            "Extension incompatible with this build",
            "The extension's declared engine_min or ir_min is newer than this engine or IR "
            "version, so loading it against this build is not sound.",
            "Upgrade Arcavex, or lower engine_min/ir_min if the extension truly supports this "
            "build.",
        ),
        _e(
            "ARC-EXT-021",
            "Extension entry could not be imported",
            "An entry module could not be imported, the named class is missing, or the component "
            "could not be constructed with no arguments — often an import-time error or an "
            "unimplemented abstract method.",
            "Check the module exists in the extension directory, defines the named class, imports "
            "only arcavex.sdk, and implements every method of its contract.",
        ),
        _e(
            "ARC-EXT-022",
            "Extension component does not match its contract",
            "A component class does not subclass the contract its kind requires, or its declared "
            "name/format attribute does not match the manifest name.",
            "Subclass the arcavex.sdk contract for the kind, and set the class name/format "
            "attribute to the manifest name so the two agree.",
        ),
        _e(
            "ARC-EXT-023",
            "Extension component parameter schema invalid",
            "An effect, mask, or shape component has no valid pydantic 'param_schema', so its "
            "authored parameters cannot be validated.",
            "Set 'param_schema' to a pydantic v2 BaseModel subclass describing the parameters.",
        ),
        _e(
            "ARC-EXT-030",
            "Extension imports outside the SDK surface",
            "A source file imports an Arcavex module other than the public 'arcavex.sdk'. This is "
            "an authoring/reliability rule, not a security boundary — extensions are insulated "
            "from engine internals so they keep working across engine changes.",
            "Import only from 'arcavex.sdk', which re-exports the contracts, helpers, and IR value "
            "types an extension may use.",
        ),
        _e(
            "ARC-EXT-031",
            "Extension uses a non-deterministic API",
            "A source file imports 'random', or a component method reads the wall clock or an "
            "undeclared file. Such use makes output depend on when or where it ran, so a rerun "
            "cannot reproduce the bytes (spec §3.2). This is a reproducibility rule, not a "
            "hostile-code check. The lint is a best-effort AST heuristic — it does not catch "
            "entropy hidden in a helper, behind an alias, or pulled in at import time — so a clean "
            "result is a reliability aid, not a guarantee.",
            "Draw randomness from the seeded 'ctx.rng' (arcavex.sdk.effect_rng); do not read the "
            "clock or undeclared files in render-affecting code.",
        ),
        _e(
            "ARC-EXT-032",
            "Extension shader failed to compile",
            "A component's SkSL shader (its 'SKSL' source) did not compile, so it would crash at "
            "render time.",
            "Fix the SkSL source; the error message reports the offending line.",
        ),
        _e(
            "ARC-EXT-040",
            "Unknown extension",
            "An enable/disable command named an extension that has not been added.",
            "Add it first with 'arcavex ext add <path>'; 'arcavex ext list' shows what is added.",
        ),
        _e(
            "ARC-EXT-050",
            "Effect bounds-expansion is dishonest",
            "A raster effect paints visibly outside the outward margin it declares via "
            "bounds_expansion, so the layout solver would not reserve enough paint region and the "
            "output would be clipped in the real pipeline.",
            "Grow bounds_expansion to cover the effect's real outward spread on every side.",
        ),
        _e(
            "ARC-EXT-051",
            "Golden output mismatch",
            "An effect's rendered output differs from its stored golden image beyond the allowed "
            "tolerance.",
            "Inspect the render; if the change is intended, regenerate the committed golden with "
            "'python golden_test.py --update' and review the image diff.",
        ),
        _e(
            "ARC-EXT-052",
            "Extension golden test failed",
            "The extension's golden_test.py exited non-zero, timed out, or is missing, so the "
            "crash-contained golden run did not pass.",
            "Run the test directly to see the failing check; the scaffold ships a golden_test.py "
            "that drives a GoldenHarness and exits non-zero on failure.",
        ),
        _e(
            "ARC-EXT-053",
            "Extension test harness could not read test output",
            "'ext test' could not start the golden_test.py subprocess, or could not read what it "
            "wrote. This is an Arcavex-side failure, so the extension's own result is unknown — it "
            "is reported apart from ARC-EXT-052, which says the extension's test really did fail.",
            "Re-run 'arcavex ext test'. If it persists, check the extension directory is readable "
            "and that the interpreter running Arcavex can start a subprocess.",
        ),
        _e(
            "ARC-EXT-060",
            "Extension scaffold or add target problem",
            "'ext scaffold' will not write into a non-empty directory, or 'ext add' could not "
            "copy the extension into the Arcavex home.",
            "Choose a new or empty scaffold directory, and ensure the Arcavex home is writable.",
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


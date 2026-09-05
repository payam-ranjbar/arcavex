"""Format/locale patch operations and locale data-overlay merge (spec §4.1.4).

Structural overrides use a small path-addressed patch language over stable node IDs rather
than a generic deep merge: the v1 operations are exactly ``set``, ``remove``,
``insert_before``, and ``insert_after``. Patches address authored node IDs (pre-repeat
expansion) and are applied to the node AST before expressions are evaluated (spec §4.1.5).
Data overlays use separately defined merge semantics: mappings merge recursively, scalars
replace, lists replace whole, an explicit ``!delete`` marker removes a key, and ``null``
remains a real value (so it never means deletion).

Each applied patch records the layer that introduced it in a :class:`PatchLog`, so
``template inspect --resolved`` can report where every value came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.kernel.ir.models import SourceRef
from arcavex.services.template.loader import line_of, node_line

_DELETE = "!delete"

#: The path root every patch layer may address: ``nodes.<id>[.<field>...]``.
NODE_ROOT = "nodes"
#: Template sections the top-level ``template patch`` operation may address besides nodes, each
#: as ``<section>.<name>[.<field>...]`` (``style`` is a whole value, so it takes no name).
TEMPLATE_SECTIONS: tuple[str, ...] = ("formats", "variables", "preview_data", "locales")
STYLE_ROOT = "style"
#: What a patch *embedded* in a format, a locale, or a project override may address. Keeping
#: these node-only is deliberate: a format patch that could rewrite ``formats`` would make the
#: layer order unreadable, and ``template inspect --resolved`` could no longer say where a
#: canvas came from.
NODES_ONLY: frozenset[str] = frozenset({NODE_ROOT})
#: What the top-level ``template patch`` operation (CLI and MCP) may address.
TEMPLATE_PATCH_ROOTS: frozenset[str] = frozenset({NODE_ROOT, *TEMPLATE_SECTIONS, STYLE_ROOT})


@dataclass
class PatchRecord:
    """One applied patch operation, the layer that introduced it, and the value it set.

    ``value`` is what *this* op assigned (only meaningful for ``set``), so ``--resolved`` can
    report what a losing layer contributed rather than only the surviving final value (RR2-10).
    """

    layer: str
    op: str
    path: str
    value: Any = None


@dataclass
class PatchLog:
    """Ordered record of applied patches, for ``--resolved`` provenance."""

    records: list[PatchRecord] = field(default_factory=list)

    def add(self, layer: str, op: str, path: str, value: Any = None) -> None:
        """Append one applied-patch record (``value`` is the value a ``set`` assigned)."""
        self.records.append(PatchRecord(layer=layer, op=op, path=path, value=value))


NodeSourceMap = dict[int, SourceRef]


def index_node_sources(
    entry: Any,
    source_file: Path,
    keypath: str,
    source_map: NodeSourceMap,
) -> None:
    """Record source provenance for every authored node mapping in ``entry``."""
    if isinstance(entry, list):
        for index, child in enumerate(entry):
            index_node_sources(
                child,
                source_file,
                f"{keypath}[{index}]",
                source_map,
            )
        return
    node = _node_of(entry)
    node_keypath = (
        f"{keypath}.node" if node is not entry else keypath
    )
    if not isinstance(node, dict):
        return
    source_map[id(node)] = SourceRef(
        file=str(source_file),
        keypath=node_keypath,
        line=line_of(node, "id") or node_line(node),
    )
    children = node.get("children")
    if isinstance(children, list):
        for index, child in enumerate(children):
            index_node_sources(
                child,
                source_file,
                f"{node_keypath}.children[{index}]",
                source_map,
            )


# --------------------------------------------------------------------------- data overlay
def is_delete(value: Any) -> bool:
    """Whether an overlay value is the ``!delete`` marker.

    Only the explicit YAML tag ``!delete`` (e.g. ``key: !delete``) removes a key; the plain
    string ``"!delete"`` is an ordinary data value, so it stays representable (CR-17).
    """
    tag = getattr(getattr(value, "tag", None), "value", None)
    return tag == _DELETE


def merge_overlay(base: Any, overlay: Any) -> Any:
    """Return ``base`` merged with ``overlay`` under the locale data-overlay semantics.

    Mappings merge key-by-key recursively; a ``!delete`` value removes the key; any other
    scalar or list replaces the base value entirely; ``null`` is a real replacement value.
    ``base`` is not mutated.
    """
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay
    out: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        key = str(key)
        if is_delete(value):
            out.pop(key, None)
            continue
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = merge_overlay(out[key], value)
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------- patches
def apply_patches(
    root_map: Any,
    ops: list[Any],
    layer: str,
    template_file: Path,
    keypath_base: str,
    log: PatchLog,
    source_map: NodeSourceMap | None = None,
    *,
    allowed_roots: frozenset[str] = NODES_ONLY,
    document: Any = None,
) -> None:
    """Apply an ordered patch list to the authored node AST in place.

    Args:
        root_map: The ``root:`` node mapping (mutated in place).
        ops: The list of patch operation mappings, applied in file order.
        layer: The layer name recorded for provenance (e.g. ``"format:a4"``).
        template_file: The source file, for located diagnostics.
        keypath_base: The keypath prefix of the patch list, for diagnostics.
        log: The provenance log to append applied operations to.
        source_map: Node provenance to extend for inserted/replaced nodes.
        allowed_roots: The path roots this layer may address. Every embedded layer (format,
            locale, project override) keeps the default ``nodes``-only grammar; the top-level
            ``template patch`` operation passes :data:`TEMPLATE_PATCH_ROOTS` so an author can
            declare a format, a variable, preview data, a locale, or the style pack.
        document: The whole template mapping, required whenever ``allowed_roots`` names a
            template section — that is where those sections live (mutated in place).
    """
    for i, op in enumerate(ops):
        kp = f"{keypath_base}[{i}]"
        if not isinstance(op, dict):
            raise _patch_error(template_file, kp, node_line(op), "each patch op must be a mapping")
        verbs = [v for v in ("set", "remove", "insert_before", "insert_after") if v in op]
        if len(verbs) != 1:
            keys = ", ".join(repr(str(k)) for k in op) or "(none)"
            raise _patch_error(
                template_file, kp, node_line(op),
                f"each patch op needs exactly one of set/remove/insert_before/insert_after "
                f"(got keys: {keys})",
            )
        verb = verbs[0]
        path = op[verb]
        line = line_of(op, verb)
        root = _path_root(path, allowed_roots, template_file, kp, line)
        if root != NODE_ROOT:
            if document is None:  # pragma: no cover - a caller bug, not an authoring error
                raise _patch_error(
                    template_file, kp, line,
                    f"patch path {path!r} addresses a template section, but this layer was "
                    "given no template document to apply it to",
                )
            _apply_section_op(document, verb, path, op, template_file, kp, line)
            log.add(layer, verb, path, op.get("value") if verb == "set" else None)
            continue
        node_id, segments = _parse_path(path)
        if verb == "set":
            value = op.get("value")
            _do_set(root_map, node_id, segments, value, template_file, kp, line)
            if source_map is not None and segments[-1:] == ["children"]:
                index_node_sources(value, template_file, f"{kp}.value", source_map)
        elif verb == "remove":
            _do_remove(root_map, node_id, segments, template_file, kp, line)
        else:
            _do_insert(root_map, node_id, op.get("node"), verb, template_file, kp, line)
            if source_map is not None:
                index_node_sources(op.get("node"), template_file, f"{kp}.node", source_map)
        log.add(layer, verb, path, op.get("value") if verb == "set" else None)


def _path_root(
    path: Any, allowed_roots: frozenset[str], file: Path, kp: str, line: int | None
) -> str:
    """Return the root a patch path addresses, refusing anything outside ``allowed_roots``.

    ``nodes`` and the four template sections need a second segment (the node id or the entry
    name); ``style`` is a whole value and stands alone.
    """
    if not isinstance(path, str) or not path:
        raise _patch_error(file, kp, line, _grammar_message(path, allowed_roots))
    parts = path.split(".")
    root = parts[0]
    if root not in allowed_roots:
        raise _patch_error(file, kp, line, _grammar_message(path, allowed_roots))
    if root != STYLE_ROOT and (len(parts) < 2 or not parts[1]):
        placeholder = "<id>" if root == NODE_ROOT else "<name>"
        raise _patch_error(
            file, kp, line,
            f"patch path {path!r} needs a {'node id' if root == NODE_ROOT else 'entry name'}: "
            f"'{root}.{placeholder}[.<field>...]'",
        )
    return root


def _grammar_message(path: Any, allowed_roots: frozenset[str]) -> str:
    if allowed_roots == NODES_ONLY:
        return (
            f"patch path {path!r} must be 'nodes.<id>[.<field>...]' (a patch embedded in a "
            "format, a locale, or a project override addresses nodes only; template sections "
            "such as 'formats' are edited with the top-level 'template patch' operation)"
        )
    return (
        f"patch path {path!r} must be 'nodes.<id>[.<field>...]', 'formats.<name>[.<field>...]', "
        "'variables.<name>[.<field>...]', 'preview_data.<key>[.<field>...]', "
        "'locales.<name>[.<field>...]', or 'style'"
    )


def _apply_section_op(
    document: Any, verb: str, path: str, op: dict[str, Any],
    file: Path, kp: str, line: int | None,
) -> None:
    """Apply a ``set``/``remove`` to a template section (``formats.<name>...``, ``style``).

    The section mapping is created when a ``set`` names an entry in a section the template
    has not declared yet (a scaffold has no ``locales:``), placed ahead of ``root:`` so the
    file still reads top-down. Deeper intermediate segments must exist, as for node fields;
    list segments take an index, so ``formats.a4.patch.0.value`` reaches one embedded op.
    """
    section, *segments = path.split(".")
    if verb in ("insert_before", "insert_after"):
        raise _patch_error(
            file, kp, line,
            f"{verb} inserts a sibling node, so its path must be 'nodes.<id>'; to add an "
            f"entry to {section!r} use 'set' with the path '{section}.<name>' and a 'value'",
        )
    if not isinstance(document, dict):
        raise _patch_error(file, kp, line, "the template root is not a mapping")
    if verb == "set":
        value = op.get("value")
        if not segments:  # the whole 'style' value
            _insert_section(document, section, value)
            return
        container = document.get(section)
        if container is None:
            container = {}
            _insert_section(document, section, container)
        target: Any = container
        for seg in segments[:-1]:
            target = _step(target, seg, file, kp, line)
        _assign(target, segments[-1], value, file, kp, line)
        return
    if section not in document:
        raise _patch_error(file, kp, line, f"unknown patch path segment {section!r}")
    if not segments:
        del document[section]
        return
    target = document[section]
    for seg in segments[:-1]:
        target = _step(target, seg, file, kp, line)
    _delete_leaf(target, segments[-1], file, kp, line)


def _insert_section(document: Any, section: str, value: Any) -> None:
    """Add (or replace) a top-level section, keeping ``root:`` the last key where possible."""
    if section in document or not hasattr(document, "insert") or "root" not in document:
        document[section] = value
        return
    position = list(document.keys()).index("root")
    document.insert(position, section, value)


def _parse_path(path: str) -> tuple[str, list[str]]:
    parts = path.split(".")
    # parts[0] == 'nodes'; parts[1] == id; rest is the field path within the node.
    return parts[1], parts[2:]


def _step(target: Any, seg: str, file: Path, kp: str, line: int | None) -> Any:
    """Walk one path segment into a mapping key or a list index.

    A numeric segment addresses a list position, so `nodes.title.effects.0.params.wow` reaches
    one effect's parameter. Without it, tuning a single effect parameter per locale meant
    replacing the whole `effects` list, which then clobbered the per-format values that list
    also carried.
    """
    if isinstance(target, list):
        try:
            index = int(seg)
        except ValueError:
            raise _patch_error(
                file, kp, line,
                f"patch path segment {seg!r} addresses a list, so it must be an index",
            ) from None
        if not -len(target) <= index < len(target):
            raise _patch_error(
                file, kp, line,
                f"patch path index {index} is out of range for a list of {len(target)}",
            )
        return target[index]
    if isinstance(target, dict) and seg in target:
        return target[seg]
    raise _patch_error(file, kp, line, f"unknown patch path segment {seg!r}")


def _assign(target: Any, seg: str, value: Any, file: Path, kp: str, line: int | None) -> None:
    """Write the final segment, into a mapping key or an existing list position."""
    if isinstance(target, list):
        try:
            index = int(seg)
        except ValueError:
            raise _patch_error(
                file, kp, line,
                f"patch path segment {seg!r} addresses a list, so it must be an index",
            ) from None
        if not -len(target) <= index < len(target):
            raise _patch_error(
                file, kp, line,
                f"patch path index {index} is out of range for a list of {len(target)}",
            )
        target[index] = value
        return
    if not isinstance(target, dict):
        raise _patch_error(file, kp, line, "patch path does not address a mapping field")
    target[seg] = value


def _do_set(
    root: Any, node_id: str, segments: list[str], value: Any,
    file: Path, kp: str, line: int | None,
) -> None:
    entry, _parent, _idx = _locate(root, node_id, file, kp, line)
    if not segments:
        raise _patch_error(file, kp, line, "set on a whole node needs a field path")
    # Field edits address the node itself, seeing through a repeat/if wrapper (CR-11).
    target = _node_of(entry)
    for seg in segments[:-1]:
        target = _step(target, seg, file, kp, line)
    # RR2-11: 'set' may add a schema-valid optional field the node omitted (e.g. a 'direction'
    # on an undirected group). The final field is created if absent; intermediate segments must
    # still exist (a whole sub-block is not conjured), and the compiler's per-block field
    # validation remains the safety net that rejects a genuinely-unknown field name downstream.
    _assign(target, segments[-1], value, file, kp, line)


def _do_remove(
    root: Any, node_id: str, segments: list[str], file: Path, kp: str, line: int | None
) -> None:
    entry, parent, idx = _locate(root, node_id, file, kp, line)
    if not segments:
        if parent is None:
            raise _patch_error(file, kp, line, "the root node cannot be removed")
        parent.pop(idx)
        return
    target = _node_of(entry)
    for seg in segments[:-1]:
        target = _step(target, seg, file, kp, line)
    _delete_leaf(target, segments[-1], file, kp, line)


def _delete_leaf(target: Any, seg: str, file: Path, kp: str, line: int | None) -> None:
    """Delete the final segment: a list position (range-checked) or an existing mapping key."""
    if isinstance(target, list):
        _step(target, seg, file, kp, line)  # range-checks, and reports the same way
        del target[int(seg)]
        return
    if not isinstance(target, dict) or seg not in target:
        raise _patch_error(file, kp, line, f"unknown patch path field {seg!r}")
    del target[seg]


def _do_insert(
    root: Any, node_id: str, new_node: Any, verb: str, file: Path, kp: str, line: int | None
) -> None:
    if not isinstance(new_node, dict):
        raise _patch_error(file, kp, line, f"{verb} needs a 'node' mapping to insert")
    _entry, parent, idx = _locate(root, node_id, file, kp, line)
    if parent is None:
        raise _patch_error(file, kp, line, "cannot insert a sibling of the root node")
    parent.insert(idx + 1 if verb == "insert_after" else idx, new_node)


def _locate(
    root: Any, node_id: str, file: Path, kp: str, line: int | None
) -> tuple[Any, list[Any] | None, int]:
    """Find a node by authored id; return (entry, parent_children_list, index_in_parent).

    The root node is addressable (parent is ``None``, CR-11); every other node is found by a
    depth-first scan of ``children``, seeing through repeat/if construct wrappers.
    """
    if isinstance(root, dict) and root.get("id") == node_id:
        return root, None, -1
    found = _search(root, node_id)
    if found is None:
        raise _patch_error(file, kp, line, f"no node with id {node_id!r} to patch")
    return found


def _search(node: Any, node_id: str) -> tuple[Any, list[Any], int] | None:
    children = node.get("children") if isinstance(node, dict) else None
    if isinstance(children, list):
        for i, child in enumerate(children):
            if isinstance(child, dict) and _child_id(child) == node_id:
                return child, children, i
            deeper = _search(_node_of(child), node_id)
            if deeper is not None:
                return deeper
    return None


def _node_of(entry: Any) -> Any:
    """Return the addressable node mapping, unwrapping a repeat/if construct wrapper."""
    if isinstance(entry, dict) and isinstance(entry.get("node"), dict) and (
        "repeat" in entry or "if" in entry
    ):
        return entry["node"]
    return entry


def read_path(root: Any, path: str) -> Any:
    """Return the value at a ``nodes.<id>[.<field>...]`` path in the (patched) AST, or None.

    Used by ``template inspect --resolved`` to read the final value a patch produced. Missing
    paths return ``None`` (a removed node/field), never raising.
    """
    if not path.startswith("nodes."):
        return None
    node_id, segments = _parse_path(path)
    if isinstance(root, dict) and root.get("id") == node_id:
        target: Any = root
    else:
        found = _search(root, node_id)
        target = _node_of(found[0]) if found is not None else None
    for seg in segments:
        if not isinstance(target, dict) or seg not in target:
            return None
        target = target[seg]
    return target


def _child_id(child: Any) -> str | None:
    """Return the authored id of a child entry, seeing through repeat/if constructs."""
    if "node" in child and isinstance(child["node"], dict):
        return child["node"].get("id")
    return child.get("id")


def _patch_error(file: Path, keypath: str, line: int | None, message: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-TPL-092",
            f"Invalid patch operation: {message}",
            file=str(file),
            keypath=keypath,
            line=line,
            hint="Patch ops are set/remove/insert_before/insert_after addressing 'nodes.<id>'.",
        )
    )

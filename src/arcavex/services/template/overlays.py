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
from arcavex.services.template.loader import line_of, node_line

_DELETE = "!delete"


@dataclass
class PatchRecord:
    """One applied patch operation and the layer that introduced it."""

    layer: str
    op: str
    path: str


@dataclass
class PatchLog:
    """Ordered record of applied patches, for ``--resolved`` provenance."""

    records: list[PatchRecord] = field(default_factory=list)

    def add(self, layer: str, op: str, path: str) -> None:
        """Append one applied-patch record."""
        self.records.append(PatchRecord(layer=layer, op=op, path=path))


# --------------------------------------------------------------------------- data overlay
def is_delete(value: Any) -> bool:
    """Whether an overlay value is the ``!delete`` marker (string or a ruamel tagged node)."""
    if value == _DELETE:
        return True
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
) -> None:
    """Apply an ordered patch list to the authored node AST in place.

    Args:
        root_map: The ``root:`` node mapping (mutated in place).
        ops: The list of patch operation mappings, applied in file order.
        layer: The layer name recorded for provenance (e.g. ``"format:a4"``).
        template_file: The source file, for located diagnostics.
        keypath_base: The keypath prefix of the patch list, for diagnostics.
        log: The provenance log to append applied operations to.
    """
    for i, op in enumerate(ops):
        kp = f"{keypath_base}[{i}]"
        if not isinstance(op, dict):
            raise _patch_error(template_file, kp, node_line(op), "each patch op must be a mapping")
        verbs = [v for v in ("set", "remove", "insert_before", "insert_after") if v in op]
        if len(verbs) != 1:
            raise _patch_error(
                template_file, kp, node_line(op),
                "each patch op needs exactly one of set/remove/insert_before/insert_after",
            )
        verb = verbs[0]
        path = op[verb]
        if not isinstance(path, str) or not path.startswith("nodes."):
            raise _patch_error(
                template_file, kp, line_of(op, verb),
                f"patch path {path!r} must be 'nodes.<id>[.<field>...]'",
            )
        node_id, segments = _parse_path(path)
        line = line_of(op, verb)
        if verb == "set":
            _do_set(root_map, node_id, segments, op.get("value"), template_file, kp, line)
        elif verb == "remove":
            _do_remove(root_map, node_id, segments, template_file, kp, line)
        else:
            _do_insert(root_map, node_id, op.get("node"), verb, template_file, kp, line)
        log.add(layer, verb, path)


def _parse_path(path: str) -> tuple[str, list[str]]:
    parts = path.split(".")
    # parts[0] == 'nodes'; parts[1] == id; rest is the field path within the node.
    return parts[1], parts[2:]


def _do_set(
    root: Any, node_id: str, segments: list[str], value: Any,
    file: Path, kp: str, line: int | None,
) -> None:
    node, _parent, _idx = _locate(root, node_id, file, kp, line)
    if not segments:
        raise _patch_error(file, kp, line, "set on a whole node needs a field path")
    target = node
    for seg in segments[:-1]:
        if not isinstance(target, dict) or seg not in target:
            raise _patch_error(file, kp, line, f"unknown patch path segment {seg!r}")
        target = target[seg]
    if not isinstance(target, dict):
        raise _patch_error(file, kp, line, "patch path does not address a mapping field")
    target[segments[-1]] = value


def _do_remove(
    root: Any, node_id: str, segments: list[str], file: Path, kp: str, line: int | None
) -> None:
    node, parent, idx = _locate(root, node_id, file, kp, line)
    if not segments:
        parent.pop(idx)
        return
    target = node
    for seg in segments[:-1]:
        if not isinstance(target, dict) or seg not in target:
            raise _patch_error(file, kp, line, f"unknown patch path segment {seg!r}")
        target = target[seg]
    if not isinstance(target, dict) or segments[-1] not in target:
        raise _patch_error(file, kp, line, f"unknown patch path field {segments[-1]!r}")
    del target[segments[-1]]


def _do_insert(
    root: Any, node_id: str, new_node: Any, verb: str, file: Path, kp: str, line: int | None
) -> None:
    if not isinstance(new_node, dict):
        raise _patch_error(file, kp, line, f"{verb} needs a 'node' mapping to insert")
    _node, parent, idx = _locate(root, node_id, file, kp, line)
    parent.insert(idx + 1 if verb == "insert_after" else idx, new_node)


def _locate(
    root: Any, node_id: str, file: Path, kp: str, line: int | None
) -> tuple[Any, list[Any], int]:
    """Find a node by authored id; return (node, parent_children_list, index_in_parent)."""
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
            deeper = _search(child, node_id)
            if deeper is not None:
                return deeper
    return None


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

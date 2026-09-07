"""Structural primitives over the authored tree: validate fully, then mutate, or raise untouched.

Every operation shares one contract: all validation happens before the first mutation, so a
raised diagnostic means the serialized document is byte-identical to what it was. The executor
relies on that to treat any refusal as "nothing happened" without re-reading the file.

What gets refused, and why:

- **Root deletion or reparenting** (``ARC-EDT-005``) — the root is the document.
- **Cycles** (``ARC-EDT-005``) — reparenting a node into its own descendant detaches the subtree
  from the document while keeping it self-referencing.
- **Unknown or invalid targets** (``ARC-EDT-004``) — a missing node, a non-group parent, a group
  of non-siblings, a group id that already exists.
- **Locked layers** (``ARC-EDT-006``) — the lock lives in project UI metadata and covers a whole
  subtree; a locked ancestor protects its children.
- **Broken sibling anchors** (``ARC-EDT-007``) — a node whose siblings anchor to it cannot be
  deleted out from under them; the dependents are named so the person can decide what to do.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.editor.source_map import NodeLocation, TreeIndex, index_tree, unwrap

#: An identifier reference inside a constraint expression: `title.bottom`, `logo.left`.
_REFERENCE = re.compile(r"\b([A-Za-z_][\w-]*)\.(?:left|right|top|bottom|start|end|h?center)\b")


# ------------------------------------------------------------------------------------- reorder


def reorder_node(root: Any, layer_id: str, *, parent_id: str, index: int) -> None:
    """Move a node among its siblings. An out-of-range index clamps to the end."""
    tree = _indexed(root)
    location = _located(tree, layer_id)
    if location.parent_id != parent_id:
        raise _invalid(
            f"Node {layer_id!r} is not a child of {parent_id!r}; use reparent to move it there."
        )
    children = location.parent_children
    entry = children.pop(location.index)
    children.insert(min(index, len(children)), entry)


# ------------------------------------------------------------------------------------ reparent


def reparent_node(root: Any, layer_id: str, *, parent_id: str, index: int) -> None:
    """Move a node (with its wrapper) under a different parent at an explicit index."""
    tree = _indexed(root)
    location = _located(tree, layer_id)
    if location.parent_id is None:
        raise _corrupting("The root node cannot be reparented.")
    new_parent = _located(tree, parent_id)
    if layer_id == parent_id or parent_id in tree.descendants(layer_id):
        raise _corrupting(
            f"Reparenting {layer_id!r} under {parent_id!r} would create a cycle: the target "
            "parent is inside the subtree being moved."
        )
    _require_group(new_parent)

    children = _ensure_children(new_parent.node)
    location.parent_children.pop(location.index)
    children.insert(min(index, len(children)), location.entry)


# -------------------------------------------------------------------------------------- delete


def delete_nodes(root: Any, layer_ids: list[str], *, locked_ids: set[str] | None = None) -> None:
    """Remove nodes and their subtrees, refusing to orphan a sibling anchor."""
    tree = _indexed(root)
    locations = [_located(tree, layer_id) for layer_id in layer_ids]
    for location in locations:
        if location.parent_id is None:
            raise _corrupting("The root node cannot be deleted.")
    _require_unlocked(tree, layer_ids, locked_ids or set())

    # Everything that will vanish: the named nodes and their descendants.
    vanishing: set[str] = set(layer_ids)
    for layer_id in layer_ids:
        vanishing |= tree.descendants(layer_id)

    _require_no_orphaned_anchors(tree, vanishing)

    # Delete deepest-first so an ancestor's removal cannot invalidate a sibling index.
    for location in sorted(locations, key=lambda entry: entry.index, reverse=True):
        if _still_present(root, location.node_id):
            fresh = index_tree(root).nodes[location.node_id]
            fresh.parent_children.pop(fresh.index)


# ----------------------------------------------------------------------------------- duplicate


def duplicate_node(root: Any, layer_id: str) -> dict[str, str]:
    """Copy a subtree immediately after the original, with fresh unique ids throughout.

    Returns:
        A mapping of every original id in the subtree to its copy's id. Internal anchor
        references between members of the subtree are rewritten to the new ids, so the copy
        moves with its own siblings rather than the originals.
    """
    tree = _indexed(root)
    location = _located(tree, layer_id)
    if location.parent_id is None:
        raise _corrupting("The root node cannot be duplicated.")

    subtree_ids = {layer_id, *tree.descendants(layer_id)}
    taken = set(tree.nodes) | tree.duplicate_ids
    renames: dict[str, str] = {}
    for original in sorted(subtree_ids):
        renames[original] = _fresh_id(original, taken)
        taken.add(renames[original])

    copied = copy.deepcopy(location.entry)
    _rewrite_subtree(copied, renames)
    location.parent_children.insert(location.index + 1, copied)
    return renames


# --------------------------------------------------------------------------------------- group


def group_nodes(root: Any, layer_ids: list[str], *, group_id: str) -> None:
    """Wrap a set of siblings in a new group node at the position of the first of them."""
    tree = _indexed(root)
    if group_id in tree.nodes or group_id in tree.duplicate_ids:
        raise _invalid(f"A node with id {group_id!r} already exists; choose a fresh group id.")
    locations = [_located(tree, layer_id) for layer_id in layer_ids]
    parents = {location.parent_id for location in locations}
    if len(parents) != 1 or None in parents:
        raise _invalid(
            "Grouping requires siblings: the selected layers do not share one parent."
        )

    children = locations[0].parent_children
    ordered = sorted(locations, key=lambda entry: entry.index)
    first_index = ordered[0].index
    entries = [children.pop(location.index) for location in reversed(ordered)]
    entries.reverse()

    group = {"id": group_id, "type": "group", "children": entries}
    children.insert(first_index, group)


# ------------------------------------------------------------------------------------ internal


def _indexed(root: Any) -> TreeIndex:
    tree = index_tree(root)
    if tree.duplicate_ids:
        raise DiagnosticError(*tree.diagnostics)
    return tree


def _located(tree: TreeIndex, layer_id: str) -> NodeLocation:
    location = tree.nodes.get(layer_id)
    if location is None:
        raise _invalid(f"No node with id {layer_id!r} exists in the authored tree.")
    return location


def _ensure_children(node: Any) -> Any:
    """The parent's child list, created empty for a group that had none yet."""
    children = node.get("children")
    if not isinstance(children, list):
        children = []
        node["children"] = children
    return children


def _require_group(parent: NodeLocation) -> None:
    kind = parent.node.get("type") if isinstance(parent.node, dict) else None
    if kind != "group":
        raise _invalid(
            f"Node {parent.node_id!r} is a {kind or 'non-group'} node and cannot hold children."
        )


def _require_unlocked(tree: TreeIndex, layer_ids: list[str], locked: set[str]) -> None:
    if not locked:
        return
    for layer_id in layer_ids:
        chain = [layer_id]
        current = tree.nodes[layer_id]
        while current.parent_id is not None:
            chain.append(current.parent_id)
            current = tree.nodes[current.parent_id]
        held = [node_id for node_id in chain if node_id in locked]
        if held:
            raise DiagnosticError(
                diagnostic(
                    "ARC-EDT-006",
                    f"Layer {layer_id!r} is protected by a lock on {held[0]!r}.",
                    hint="Unlock the layer in the Layers panel, or edit something else.",
                )
            )


def _require_no_orphaned_anchors(tree: TreeIndex, vanishing: set[str]) -> None:
    dependents: dict[str, list[str]] = {}
    for node_id, location in tree.nodes.items():
        if node_id in vanishing:
            continue
        for target in _anchor_references(location.node):
            if target in vanishing:
                dependents.setdefault(target, []).append(node_id)
    if dependents:
        details = "; ".join(
            f"{', '.join(sorted(nodes))} anchor(s) to {target!r}"
            for target, nodes in sorted(dependents.items())
        )
        raise DiagnosticError(
            diagnostic(
                "ARC-EDT-007",
                f"Deleting would orphan sibling anchors: {details}.",
                hint=(
                    "Delete the dependent layers too, or re-anchor them to another sibling "
                    "first."
                ),
            )
        )


def _anchor_references(node: Any) -> set[str]:
    """Every sibling id this node's constraint expressions mention."""
    references: set[str] = set()
    constraints = node.get("constraints") if isinstance(node, dict) else None
    if not isinstance(constraints, dict):
        return references
    for section in constraints.values():
        values = section.values() if isinstance(section, dict) else [section]
        for value in values:
            if isinstance(value, str):
                for match in _REFERENCE.finditer(value):
                    if match.group(1) != "parent":
                        references.add(match.group(1))
    return references


def _rewrite_subtree(entry: Any, renames: dict[str, str]) -> None:
    """Rename ids and rewrite internal anchor references throughout a copied subtree."""
    node = unwrap(entry)
    if not isinstance(node, dict):
        return
    original = node.get("id")
    if isinstance(original, str) and original in renames:
        node["id"] = renames[original]
    constraints = node.get("constraints")
    if isinstance(constraints, dict):
        for section in constraints.values():
            if isinstance(section, dict):
                for key, value in section.items():
                    if isinstance(value, str):
                        section[key] = _rewrite_references(value, renames)
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            _rewrite_subtree(child, renames)


def _rewrite_references(expression: str, renames: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        target = match.group(1)
        renamed = renames.get(target, target)
        return match.group(0).replace(target, renamed, 1)

    return _REFERENCE.sub(replace, expression)


def _fresh_id(original: str, taken: set[str]) -> str:
    candidate = f"{original}-copy"
    serial = 2
    while candidate in taken:
        candidate = f"{original}-copy-{serial}"
        serial += 1
    return candidate


def _still_present(root: Any, node_id: str) -> bool:
    return node_id in index_tree(root).nodes


def _invalid(message: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-EDT-004",
            message,
            hint="Inspect the layer tree for current ids and structure, then retry.",
        )
    )


def _corrupting(message: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-EDT-005",
            message,
            hint="This operation is never valid; nothing was changed.",
        )
    )

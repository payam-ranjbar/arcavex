"""The source map: every stable authored node, located with its parent and position.

Structural edits address nodes by stable id, but the mutation itself happens in a parent's child
list at an index. This map is the bridge, and it deliberately does not flatten the two authored
wrappers — a ``repeat`` or ``if`` construct entry wraps its node — because the wrapper is what
must move when its node is reordered. Flattening it would silently unroll the loop.

Built on the loaded ruamel AST so the located mappings are the same objects the tree primitives
mutate and the round-trip writer serializes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arcavex.kernel.diagnostics import Diagnostic, diagnostic


@dataclass(frozen=True)
class NodeLocation:
    """One authored node: the mapping itself, its wrapper entry, and where it sits."""

    node_id: str
    #: The addressable node mapping (inside its wrapper, when wrapped).
    node: Any
    #: The entry that actually sits in the parent's child list — the wrapper for a repeat/if
    #: construct, the node itself otherwise.
    entry: Any
    parent_id: str | None
    #: The parent's ruamel child list, or ``None`` for the root.
    parent_children: Any
    #: Index of ``entry`` in ``parent_children``; ``-1`` for the root.
    index: int


@dataclass(frozen=True)
class TreeIndex:
    """Every located node plus the problems found while indexing."""

    nodes: dict[str, NodeLocation]
    #: Child ids per parent id, in authored order.
    children_of: dict[str, list[str]]
    duplicate_ids: set[str]
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def descendants(self, node_id: str) -> set[str]:
        """Every id under ``node_id``, exclusive of it — the cycle question."""
        collected: set[str] = set()
        frontier = list(self.children_of.get(node_id, []))
        while frontier:
            current = frontier.pop()
            if current in collected:
                continue
            collected.add(current)
            frontier.extend(self.children_of.get(current, []))
        return collected


def unwrap(entry: Any) -> Any:
    """Return the addressable node of a child entry, seeing through repeat/if wrappers."""
    if isinstance(entry, dict) and isinstance(entry.get("node"), dict) and (
        "repeat" in entry or "if" in entry
    ):
        return entry["node"]
    return entry


def index_tree(root: Any) -> TreeIndex:
    """Index the authored tree from its (possibly ruamel) root mapping."""
    nodes: dict[str, NodeLocation] = {}
    children_of: dict[str, list[str]] = {}
    duplicates: set[str] = set()

    def register(location: NodeLocation) -> None:
        if location.node_id in nodes:
            duplicates.add(location.node_id)
            return
        nodes[location.node_id] = location

    def walk(node: Any, node_id: str) -> None:
        children = node.get("children") if isinstance(node, dict) else None
        if not isinstance(children, list):
            return
        ordered: list[str] = []
        for index, entry in enumerate(children):
            child = unwrap(entry)
            child_id = child.get("id") if isinstance(child, dict) else None
            if not isinstance(child_id, str) or not child_id:
                continue
            ordered.append(child_id)
            register(
                NodeLocation(
                    node_id=child_id,
                    node=child,
                    entry=entry,
                    parent_id=node_id,
                    parent_children=children,
                    index=index,
                )
            )
            walk(child, child_id)
        children_of[node_id] = ordered

    root_id = root.get("id") if isinstance(root, dict) else None
    if isinstance(root_id, str) and root_id:
        register(
            NodeLocation(
                node_id=root_id,
                node=root,
                entry=root,
                parent_id=None,
                parent_children=None,
                index=-1,
            )
        )
        walk(root, root_id)

    diagnostics = [
        diagnostic(
            "ARC-EDT-004",
            f"Duplicate authored id {node_id!r}: structural edits cannot address it "
            "unambiguously.",
            hint="Give every node a unique 'id' before editing structurally.",
        )
        for node_id in sorted(duplicates)
    ]
    return TreeIndex(
        nodes=nodes,
        children_of=children_of,
        duplicate_ids=duplicates,
        diagnostics=diagnostics,
    )

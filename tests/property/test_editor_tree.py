"""Tree-operation invariants under random structure: what must hold no matter the shape.

Two properties carry the whole editing model:

1. A successful structural operation preserves a well-formed document — every id unique, every
   node reachable from the root, no cycles.
2. A refused operation leaves the serialized bytes identical, because the executor treats any
   raised diagnostic as "nothing happened" without re-reading the file.

The example tests pin specific behaviours; these hunt the shapes nobody thought to write down.
"""

from __future__ import annotations

import io
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from ruamel.yaml import YAML

from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.editor.source_map import index_tree
from arcavex.services.editor.tree import (
    delete_nodes,
    duplicate_node,
    group_nodes,
    reorder_node,
    reparent_node,
)


def _tree_strategy() -> st.SearchStrategy[dict[str, Any]]:
    """Random authored trees: nested groups and leaves with unique ids n0, n1, ..."""

    def build(shape: list[Any], counter: list[int]) -> dict[str, Any]:
        node_id = f"n{counter[0]}"
        counter[0] += 1
        node: dict[str, Any] = {"id": node_id, "type": "group", "children": []}
        for child_shape in shape:
            if isinstance(child_shape, list):
                node["children"].append(build(child_shape, counter))
            else:
                leaf_id = f"n{counter[0]}"
                counter[0] += 1
                node["children"].append({"id": leaf_id, "type": "text", "text": "x"})
        return node

    shapes = st.recursive(
        st.integers(min_value=0, max_value=2),
        lambda inner: st.lists(inner, min_size=0, max_size=3),
        max_leaves=12,
    ).filter(lambda shape: isinstance(shape, list))
    return shapes.map(lambda shape: build(shape, [0]))


def _reload(tree: dict[str, Any]) -> Any:
    """Round-trip through YAML so operations run against ruamel structures, as in production."""
    yaml = YAML()
    buffer = io.StringIO()
    yaml.dump(tree, buffer)
    return yaml.load(io.StringIO(buffer.getvalue()))


def _dump(root: Any) -> str:
    buffer = io.StringIO()
    YAML().dump(root, buffer)
    return buffer.getvalue()


def _well_formed(root: Any) -> None:
    index = index_tree(root)
    assert not index.duplicate_ids, f"duplicate ids after an accepted operation: {index}"
    root_id = root["id"]
    reachable = {root_id} | index.descendants(root_id)
    assert reachable == set(index.nodes), "every node must stay reachable from the root"


@settings(max_examples=60, deadline=None)
@given(tree=_tree_strategy(), data=st.data())
def test_accepted_operations_preserve_a_well_formed_tree(
    tree: dict[str, Any], data: st.DataObject
) -> None:
    root = _reload(tree)
    index = index_tree(root)
    ids = sorted(index.nodes)
    operation = data.draw(
        st.sampled_from(["reorder", "reparent", "delete", "duplicate", "group"])
    )
    subject = data.draw(st.sampled_from(ids))
    target = data.draw(st.sampled_from(ids))
    position = data.draw(st.integers(min_value=0, max_value=6))

    try:
        if operation == "reorder":
            parent = index.nodes[subject].parent_id
            if parent is None:
                return
            reorder_node(root, subject, parent_id=parent, index=position)
        elif operation == "reparent":
            reparent_node(root, subject, parent_id=target, index=position)
        elif operation == "delete":
            delete_nodes(root, [subject])
        elif operation == "duplicate":
            duplicate_node(root, subject)
        else:
            siblings = [
                node_id
                for node_id in ids
                if index.nodes[node_id].parent_id == index.nodes[subject].parent_id
                and index.nodes[node_id].parent_id is not None
            ]
            if not siblings:
                return
            group_nodes(root, siblings[:2], group_id="fresh-group")
    except DiagnosticError:
        return  # refusals are covered by the bytes-identical property below

    _well_formed(root)


@settings(max_examples=60, deadline=None)
@given(tree=_tree_strategy(), data=st.data())
def test_refused_operations_leave_the_document_byte_identical(
    tree: dict[str, Any], data: st.DataObject
) -> None:
    root = _reload(tree)
    index = index_tree(root)
    ids = sorted(index.nodes)
    root_id = root["id"]
    before = _dump(root)

    # Draw from operations that are guaranteed to be refused.
    refusal = data.draw(st.sampled_from(["delete-root", "reparent-root", "cycle", "unknown"]))
    try:
        if refusal == "delete-root":
            delete_nodes(root, [root_id])
        elif refusal == "reparent-root":
            reparent_node(root, root_id, parent_id=data.draw(st.sampled_from(ids)), index=0)
        elif refusal == "cycle":
            groups = [i for i in ids if index.nodes[i].node.get("type") == "group"]
            subject = data.draw(st.sampled_from(groups))
            below = sorted(index.descendants(subject))
            if not below:
                return
            reparent_node(root, subject, parent_id=data.draw(st.sampled_from(below)), index=0)
        else:
            delete_nodes(root, ["no-such-node"])
    except DiagnosticError:
        assert _dump(root) == before
        return

    raise AssertionError(f"{refusal} was expected to be refused")

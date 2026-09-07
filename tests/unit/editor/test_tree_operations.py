"""Structural primitives over the authored tree: what they do, and what they refuse.

Every operation here mutates a ruamel AST in place — but only after full validation, so a refusal
leaves the serialized document byte-identical. That property is what lets the executor treat any
raised diagnostic as "nothing happened" without re-reading the file.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from ruamel.yaml import YAML

from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.editor.tree import (
    delete_nodes,
    duplicate_node,
    group_nodes,
    reorder_node,
    reparent_node,
)

_TEMPLATE = """\
id: root
type: group
children:
  - id: header
    type: group
    children:
      - id: logo    # keep me
        type: image
      - id: title
        type: text
        constraints:
          anchor: {top: parent.top+10pt, left: parent.left}
  - id: subtitle
    type: text
    constraints:
      anchor: {top: title.bottom+8pt, left: title.left}
  - id: badge
    type: shape
  - repeat:
      over: items
      as: item
    node:
      id: card
      type: group
"""


def _load(text: str = _TEMPLATE) -> Any:
    return YAML().load(io.StringIO(text))


def _dump(root: Any) -> str:
    buffer = io.StringIO()
    YAML().dump(root, buffer)
    return buffer.getvalue()


def _ids_in_order(root: Any) -> list[str]:
    from arcavex.services.editor.source_map import index_tree

    tree = index_tree(root)
    return sorted(tree.nodes)


# ------------------------------------------------------------------------------------- reorder


def test_reorder_moves_a_node_among_its_siblings() -> None:
    root = _load()

    reorder_node(root, "badge", parent_id="root", index=0)

    children = [child.get("id") or child["node"]["id"] for child in root["children"]]
    assert children == ["badge", "header", "subtitle", "card"]


def test_reorder_moves_a_wrapped_node_with_its_wrapper() -> None:
    root = _load()

    reorder_node(root, "card", parent_id="root", index=0)

    first = root["children"][0]
    assert "repeat" in first and first["node"]["id"] == "card"


def test_reorder_to_an_out_of_range_index_clamps_to_the_end() -> None:
    root = _load()

    reorder_node(root, "header", parent_id="root", index=99)

    last = root["children"][-1]
    assert last.get("id") == "header"


# ------------------------------------------------------------------------------------ reparent


def test_reparent_moves_a_node_under_a_new_parent_at_the_index() -> None:
    root = _load()

    reparent_node(root, "badge", parent_id="header", index=1)

    header = root["children"][0]
    assert [child["id"] for child in header["children"]] == ["logo", "badge", "title"]


def test_reparent_into_a_descendant_is_a_refused_cycle() -> None:
    root = _load()
    before = _dump(root)

    with pytest.raises(DiagnosticError) as raised:
        reparent_node(root, "header", parent_id="logo", index=0)

    assert raised.value.diagnostics[0].code == "ARC-EDT-005"
    assert _dump(root) == before


def test_the_root_cannot_be_reparented_or_deleted() -> None:
    root = _load()
    before = _dump(root)

    for operation in (
        lambda: reparent_node(root, "root", parent_id="header", index=0),
        lambda: delete_nodes(root, ["root"]),
    ):
        with pytest.raises(DiagnosticError) as raised:
            operation()
        assert raised.value.diagnostics[0].code == "ARC-EDT-005"
    assert _dump(root) == before


def test_reparent_under_a_non_group_is_refused() -> None:
    root = _load()
    before = _dump(root)

    with pytest.raises(DiagnosticError) as raised:
        reparent_node(root, "badge", parent_id="title", index=0)

    assert raised.value.diagnostics[0].code == "ARC-EDT-004"
    assert _dump(root) == before


# -------------------------------------------------------------------------------------- delete


def test_delete_removes_the_node_and_its_subtree() -> None:
    """subtitle rides along because it anchors to title inside header's subtree — deleting
    header alone is correctly refused by the anchor guard, which has its own test below."""
    root = _load()

    delete_nodes(root, ["header", "subtitle"])

    remaining = _ids_in_order(root)
    assert "header" not in remaining
    assert "logo" not in remaining, "descendants go with their subtree"
    assert "badge" in remaining


def test_delete_refuses_a_node_a_sibling_anchor_depends_on() -> None:
    """subtitle anchors to title.bottom; deleting title would orphan that expression."""
    root = _load()
    before = _dump(root)

    with pytest.raises(DiagnosticError) as raised:
        delete_nodes(root, ["title"])

    diagnostic = raised.value.diagnostics[0]
    assert diagnostic.code == "ARC-EDT-007"
    assert "subtitle" in diagnostic.message
    assert _dump(root) == before


def test_deleting_the_dependent_and_its_anchor_target_together_is_allowed() -> None:
    root = _load()

    delete_nodes(root, ["title", "subtitle"])

    remaining = _ids_in_order(root)
    assert "title" not in remaining and "subtitle" not in remaining


def test_delete_refuses_a_locked_layer() -> None:
    root = _load()
    before = _dump(root)

    with pytest.raises(DiagnosticError) as raised:
        delete_nodes(root, ["badge"], locked_ids={"badge"})

    assert raised.value.diagnostics[0].code == "ARC-EDT-006"
    assert _dump(root) == before


def test_a_locked_ancestor_protects_its_subtree() -> None:
    root = _load()
    before = _dump(root)

    with pytest.raises(DiagnosticError) as raised:
        delete_nodes(root, ["logo"], locked_ids={"header"})

    assert raised.value.diagnostics[0].code == "ARC-EDT-006"
    assert _dump(root) == before


# ----------------------------------------------------------------------------------- duplicate


def test_duplicate_copies_the_subtree_with_fresh_unique_ids() -> None:
    root = _load()

    new_ids = duplicate_node(root, "header")

    ids = _ids_in_order(root)
    assert len(ids) == len(set(ids)), "every id must stay unique"
    assert new_ids["header"] in ids and new_ids["header"] != "header"
    assert new_ids["logo"] in ids and new_ids["logo"] != "logo"
    # The copy sits immediately after the original.
    order = [child.get("id") or child["node"]["id"] for child in root["children"]]
    assert order.index(new_ids["header"]) == order.index("header") + 1


def test_duplicate_rewrites_internal_anchor_references_to_the_new_ids() -> None:
    """A copied subtree that still anchors to the original would move with the wrong sibling."""
    root = _load()
    # Make header's title anchor to its sibling logo, an internal reference.
    header = root["children"][0]
    header["children"][1]["constraints"]["anchor"]["top"] = "logo.bottom+4pt"

    new_ids = duplicate_node(root, "header")

    from arcavex.services.editor.source_map import index_tree

    copied_title = index_tree(root).nodes[new_ids["title"]].node
    assert copied_title["constraints"]["anchor"]["top"] == f"{new_ids['logo']}.bottom+4pt"


# --------------------------------------------------------------------------------------- group


def test_group_wraps_siblings_in_a_new_group_at_the_first_position() -> None:
    root = _load()

    group_nodes(root, ["subtitle", "badge"], group_id="callout")

    order = [child.get("id") or child["node"]["id"] for child in root["children"]]
    assert order == ["header", "callout", "card"]
    callout = root["children"][1]
    assert callout["type"] == "group"
    assert [child["id"] for child in callout["children"]] == ["subtitle", "badge"]


def test_group_refuses_non_siblings() -> None:
    root = _load()
    before = _dump(root)

    with pytest.raises(DiagnosticError) as raised:
        group_nodes(root, ["logo", "badge"], group_id="mixed")

    assert raised.value.diagnostics[0].code == "ARC-EDT-004"
    assert _dump(root) == before


def test_group_refuses_an_id_that_already_exists() -> None:
    root = _load()
    before = _dump(root)

    with pytest.raises(DiagnosticError) as raised:
        group_nodes(root, ["subtitle", "badge"], group_id="title")

    assert raised.value.diagnostics[0].code == "ARC-EDT-004"
    assert _dump(root) == before


# ------------------------------------------------------------------------------- preservation


def test_operations_preserve_comments_elsewhere_in_the_document() -> None:
    root = _load()

    reorder_node(root, "badge", parent_id="root", index=0)

    assert "# keep me" in _dump(root)

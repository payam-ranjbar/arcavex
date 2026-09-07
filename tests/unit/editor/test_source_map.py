"""The source map: every stable authored node, findable with its parent and position.

Structural edits address nodes by stable id, but they mutate a parent's child list at an index.
The map is the bridge — and it must see through the two wrappers the authored tree uses (`repeat`
and `if` construct entries) without flattening them, because the wrapper is what must move when
its node is reordered.
"""

from __future__ import annotations

import io
from typing import Any

from ruamel.yaml import YAML

from arcavex.services.editor.source_map import index_tree

_TEMPLATE = """\
id: root
type: group
children:
  - id: header
    type: group
    children:
      - id: logo          # a comment that must survive round-trips
        type: image
      - id: title
        type: text
  - repeat:
      over: items
      as: item
    node:
      id: card
      type: group
      children:
        - id: card-label
          type: text
  - if: "show_badge"
    node:
      id: badge
      type: shape
"""


def _load(text: str = _TEMPLATE) -> Any:
    return YAML().load(io.StringIO(text))


def test_every_authored_node_is_indexed_with_parent_and_position() -> None:
    tree = index_tree(_load())

    assert set(tree.nodes) == {"root", "header", "logo", "title", "card", "card-label", "badge"}
    logo = tree.nodes["logo"]
    assert logo.parent_id == "header"
    assert logo.index == 0
    title = tree.nodes["title"]
    assert title.parent_id == "header"
    assert title.index == 1


def test_the_root_has_no_parent() -> None:
    tree = index_tree(_load())

    root = tree.nodes["root"]
    assert root.parent_id is None
    assert root.parent_children is None


def test_a_wrapped_node_is_indexed_but_its_wrapper_is_what_sits_in_the_child_list() -> None:
    """Moving `card` must move its repeat wrapper, or the loop would be silently unrolled."""
    tree = index_tree(_load())

    card = tree.nodes["card"]
    assert card.parent_id == "root"
    assert card.index == 1
    entry = card.parent_children[card.index]  # type: ignore[index]
    assert "repeat" in entry, "the list entry is the wrapper, not the bare node"
    assert entry["node"]["id"] == "card"

    badge = tree.nodes["badge"]
    assert "if" in badge.parent_children[badge.index]  # type: ignore[index]


def test_children_of_a_wrapped_node_are_reachable() -> None:
    tree = index_tree(_load())

    label = tree.nodes["card-label"]
    assert label.parent_id == "card"


def test_a_duplicate_id_is_reported_not_silently_shadowed() -> None:
    duplicated = _TEMPLATE.replace("id: badge", "id: title")
    tree = index_tree(_load(duplicated))

    assert any(diag.code == "ARC-EDT-004" for diag in tree.diagnostics)
    assert "title" in tree.duplicate_ids


def test_descendants_answer_the_cycle_question() -> None:
    tree = index_tree(_load())

    assert tree.descendants("header") == {"logo", "title"}
    assert "card-label" in tree.descendants("root")
    assert tree.descendants("badge") == set()

"""Format/locale patch operation tests (spec §4.1.4)."""

from __future__ import annotations

from pathlib import Path

from arcavex.kernel.diagnostics import has_errors
from arcavex.services.template.compiler import Compiler

_BASE = """
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
  patched:
    canvas: {width: 200px, height: 200px, dpi: 72}
    patch:
%s
root:
  type: group
  id: root
  children:
    - id: a
      type: shape
      shape: rect
      style: {fill: "#ffffff", opacity: 1.0}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 50pt, h: 50pt}}
    - id: b
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 50pt, h: 50pt}}
"""


def _compile(tmp_path: Path, patch_body: str, fmt: str = "patched"):  # noqa: ANN202
    template = tmp_path / "t.yaml"
    template.write_text(_BASE % patch_body, encoding="utf-8")
    return Compiler().compile(template, None, fmt, None, None)


def _children(doc) -> list:  # noqa: ANN001
    return list(doc.root.children)


def test_set_operation(tmp_path: Path) -> None:
    result = _compile(tmp_path, "      - set: nodes.a.style.opacity\n        value: 0.25\n")
    assert result.document is not None, result.diagnostics
    assert _children(result.document)[0].style.opacity == 0.25


def test_remove_operation(tmp_path: Path) -> None:
    result = _compile(tmp_path, "      - remove: nodes.b\n")
    assert result.document is not None, result.diagnostics
    ids = [c.id for c in _children(result.document)]
    assert ids == ["a"]


def test_insert_before_and_after(tmp_path: Path) -> None:
    patch = (
        "      - insert_before: nodes.a\n"
        "        node: {id: pre, type: shape, shape: rect,"
        " constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 5pt, h: 5pt}}}\n"
        "      - insert_after: nodes.b\n"
        "        node: {id: post, type: shape, shape: rect,"
        " constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 5pt, h: 5pt}}}\n"
    )
    result = _compile(tmp_path, patch)
    assert result.document is not None, result.diagnostics
    assert [c.id for c in _children(result.document)] == ["pre", "a", "b", "post"]


def test_operations_apply_in_file_order(tmp_path: Path) -> None:
    # set opacity to 0.5, then to 0.9: the last write wins.
    patch = (
        "      - set: nodes.a.style.opacity\n        value: 0.5\n"
        "      - set: nodes.a.style.opacity\n        value: 0.9\n"
    )
    result = _compile(tmp_path, patch)
    assert result.document is not None, result.diagnostics
    assert _children(result.document)[0].style.opacity == 0.9


def test_unknown_path_is_error(tmp_path: Path) -> None:
    result = _compile(tmp_path, "      - set: nodes.ghost.style.opacity\n        value: 0.5\n")
    assert any(d.code == "ARC-TPL-092" for d in result.diagnostics)


def test_remove_then_insert(tmp_path: Path) -> None:
    patch = (
        "      - remove: nodes.a\n"
        "      - insert_after: nodes.b\n"
        "        node: {id: c, type: shape, shape: rect,"
        " constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 5pt, h: 5pt}}}\n"
    )
    result = _compile(tmp_path, patch)
    assert result.document is not None, result.diagnostics
    assert [c.id for c in _children(result.document)] == ["b", "c"]


def test_unpatched_format_unaffected(tmp_path: Path) -> None:
    # The 'square' format has no patch, so 'a' keeps its authored opacity.
    result = _compile(
        tmp_path, "      - set: nodes.a.style.opacity\n        value: 0.25\n", "square"
    )
    assert result.document is not None, result.diagnostics
    assert not has_errors(result.diagnostics)
    assert _children(result.document)[0].style.opacity == 1.0

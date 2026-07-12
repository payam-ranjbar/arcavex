"""Structural construct tests: repeat/if compile-time expansion (spec §4.1.2)."""

from __future__ import annotations

from pathlib import Path

from arcavex.services.template.compiler import Compiler


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "template.yaml"
    path.write_text(body, encoding="utf-8")
    return path


_REPEAT = """
version: 0.1.0
formats: {square: {canvas: {width: 400px, height: 400px, dpi: 96}}}
preview_data:
  guests:
    - {id: ann, name: Ann}
    - {id: bo, name: Bo}
root:
  type: group
  id: root
  children:
    - repeat: "{{ guests }}"
      as: guest
      key: "{{ guest.id }}"
      node:
        type: text
        id: name
        text: "{{ guest.name }}"
        style: {font: Inter, font_size: 20px, color: white}
        constraints:
          anchor: {top: parent.top, left: parent.left}
          size: {w: fill, h: fit_content}
"""


def _ids(node) -> list[str]:
    out = [node.id]
    for child in getattr(node, "children", ()):
        out.extend(_ids(child))
    return out


def test_repeat_expands_with_stable_keyed_ids(tmp_path: Path) -> None:
    result = Compiler().compile(_write(tmp_path, _REPEAT), None, "square", None, None)
    assert result.document is not None
    ids = _ids(result.document.root)
    assert ids == ["root", "name[ann]", "name[bo]"]


def test_repeat_ids_are_key_based_not_index(tmp_path: Path) -> None:
    """Reordering the data reorders nodes but keeps the same keyed IDs (stability)."""
    template = _write(tmp_path, _REPEAT)
    data = tmp_path / "data.yaml"
    data.write_text(
        "guests:\n  - {id: bo, name: Bo}\n  - {id: ann, name: Ann}\n", encoding="utf-8"
    )
    result = Compiler().compile(template, data, "square", None, None)
    assert result.document is not None
    assert _ids(result.document.root) == ["root", "name[bo]", "name[ann]"]


def test_repeat_duplicate_key_is_error(tmp_path: Path) -> None:
    template = _write(tmp_path, _REPEAT)
    data = tmp_path / "data.yaml"
    data.write_text(
        "guests:\n  - {id: x, name: A}\n  - {id: x, name: B}\n", encoding="utf-8"
    )
    result = Compiler().compile(template, data, "square", None, None)
    assert result.document is None
    assert any(d.code == "ARC-TPL-058" for d in result.diagnostics)


def test_repeat_missing_key_is_error(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
preview_data: {items: [1, 2]}
root:
  type: group
  id: root
  children:
    - repeat: "{{ items }}"
      as: it
      node:
        type: text
        id: t
        text: "{{ it }}"
        style: {font_size: 8px, color: white}
        constraints:
          anchor: {top: parent.top, left: parent.left}
          size: {w: fill, h: fit_content}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-TPL-055" for d in result.diagnostics)


def test_repeat_index_key_warns_but_compiles(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
preview_data: {items: [1, 2, 3]}
root:
  type: group
  id: root
  children:
    - repeat: "{{ items }}"
      as: it
      key: "{{ loop.index }}"
      node:
        type: text
        id: t
        text: "{{ it }}"
        style: {font_size: 8px, color: white}
        constraints:
          anchor: {top: parent.top, left: parent.left}
          size: {w: fill, h: fit_content}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None
    warnings = [d for d in result.diagnostics if not d.is_error()]
    assert any(d.code == "ARC-TPL-057" for d in warnings)
    assert _ids(result.document.root) == ["root", "t[0]", "t[1]", "t[2]"]


def test_repeat_cap_exceeded(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
root:
  type: group
  id: root
  children:
    - repeat: "{{ items }}"
      as: it
      key: "{{ loop.index }}"
      node:
        type: text
        id: t
        text: "x"
        style: {font_size: 8px, color: white}
        constraints:
          anchor: {top: parent.top, left: parent.left}
          size: {w: fill, h: fit_content}
""",
    )
    data = tmp_path / "data.yaml"
    data.write_text("items: [" + ",".join("0" for _ in range(1001)) + "]\n", encoding="utf-8")
    result = Compiler().compile(template, data, "square", None, None)
    assert any(d.code == "ARC-TPL-063" for d in result.diagnostics)


def test_if_includes_and_excludes(tmp_path: Path) -> None:
    body = """
version: 0.1.0
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
variables: {footer: {type: string, required: false}}
root:
  type: group
  id: root
  children:
    - if: "{{ footer is not none }}"
      node:
        type: text
        id: foot
        text: "{{ footer }}"
        style: {font_size: 8px, color: white}
        constraints:
          anchor: {bottom: parent.bottom, left: parent.left}
          size: {w: fill, h: fit_content}
"""
    template = _write(tmp_path, body)
    # footer present -> node included
    data = tmp_path / "d1.yaml"
    data.write_text("footer: hello\n", encoding="utf-8")
    r1 = Compiler().compile(template, data, "square", None, None)
    assert r1.document is not None and _ids(r1.document.root) == ["root", "foot"]
    # footer absent -> node excluded
    empty = tmp_path / "d2.yaml"
    empty.write_text("other: 1\n", encoding="utf-8")
    r2 = Compiler().compile(template, empty, "square", None, None)
    assert r2.document is not None and _ids(r2.document.root) == ["root"]


def test_nested_repeats_compose_ids(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 400px, height: 400px, dpi: 96}}}
preview_data:
  groups:
    - {id: g1, rows: [{id: r1}, {id: r2}]}
root:
  type: group
  id: root
  children:
    - repeat: "{{ groups }}"
      as: g
      key: "{{ g.id }}"
      node:
        type: group
        id: grp
        constraints:
          anchor: {top: parent.top, left: parent.left}
          size: {w: fill, h: fill}
        children:
          - repeat: "{{ g.rows }}"
            as: row
            key: "{{ row.id }}"
            node:
              type: text
              id: cell
              text: "{{ row.id }}"
              style: {font_size: 8px, color: white}
              constraints:
                anchor: {top: parent.top, left: parent.left}
                size: {w: fill, h: fit_content}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None
    ids = _ids(result.document.root)
    assert ids == ["root", "grp[g1]", "cell[g1][r1]", "cell[g1][r2]"]

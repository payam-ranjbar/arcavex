"""Guarding tests for the Phase 1 remediation (CR-* / DX-*).

Each test pins a specific finding from the Phase 1 code and DX reviews so the fix cannot
silently regress. Compiler-level behaviors use the isolated :class:`Compiler`; facade-level
behaviors (default output naming, preview paths, inspect) use the fully wired facade.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.services.template.compiler import Compiler

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELLO = _REPO_ROOT / "examples" / "hello-poster"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "template.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _codes(result) -> list[str]:
    return [d.code for d in result.diagnostics]


# ------------------------------------------------------------------ CR-3: repeat + if
def test_repeat_and_if_on_same_child_is_error(tmp_path: Path) -> None:
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
      key: "{{ loop.index }}"
      if: "{{ false }}"
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
    assert "ARC-TPL-061" in _codes(result)


# ------------------------------------------------------------- CR-5: explicit null optional
def _null_template(tmp_path: Path, required: str) -> Path:
    return _write(
        tmp_path,
        "version: 0.1.0\n"
        f"variables: {{s: {{type: string, required: {required}}}}}\n"
        "formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root:\n"
        "  type: group\n"
        "  id: root\n"
        "  children:\n"
        "    - if: \"{{ s is not none }}\"\n"
        "      node:\n"
        "        id: t\n"
        "        type: text\n"
        "        text: \"{{ s }}\"\n"
        "        style: {font_size: 8px, color: white}\n"
        "        constraints:\n"
        "          anchor: {top: parent.top, left: parent.left}\n"
        "          size: {w: fill, h: fit_content}\n",
    )


def test_explicit_null_optional_equals_omission(tmp_path: Path) -> None:
    template = _null_template(tmp_path, "false")
    data = tmp_path / "data.yaml"
    data.write_text("s:\n", encoding="utf-8")  # YAML 's:' with empty value is null
    result = Compiler().compile(template, data, "square", None, None)
    assert result.document is not None
    assert "ARC-TPL-015" not in _codes(result)  # no "should be string but got NoneType"
    # Bound to None, so the `is not none` guard drops the node.
    assert [n.id for n in result.document.root.children] == []


def test_explicit_null_required_still_errors(tmp_path: Path) -> None:
    template = _null_template(tmp_path, "true")
    data = tmp_path / "data.yaml"
    data.write_text("s:\n", encoding="utf-8")
    result = Compiler().compile(template, data, "square", None, None)
    assert "ARC-TPL-014" in _codes(result)


# ------------------------------------------------------------- CR-8: data-file line numbers
def test_data_file_line_is_cited(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        "version: 0.1.0\n"
        "variables: {count: {type: number, required: true}}\n"
        "formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root: {type: group, id: root, children: []}\n",
    )
    data = tmp_path / "data.yaml"
    data.write_text("# a comment\ncount: not-a-number\n", encoding="utf-8")
    result = Compiler().compile(template, data, "square", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-015")
    assert diag.source is not None
    assert diag.source.file == str(data)
    assert diag.source.line == 2  # the 'count:' line in the data file, not None


# --------------------------------------------------------------- DX-1a: overlap warning
def test_repeat_overlap_warns(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 400px, height: 400px, dpi: 96}}}
preview_data: {tags: [a, b, c]}
root:
  type: group
  id: root
  children:
    - repeat: "{{ tags }}"
      as: tag
      key: "{{ tag }}"
      node:
        id: chip
        type: text
        text: "{{ tag }}"
        style: {font_size: 12px, color: white}
        constraints:
          anchor: {top: parent.top, left: parent.left}
          size: {w: fit_content, h: fit_content}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None  # warning does not block compilation
    warn = next(d for d in result.diagnostics if d.code == "ARC-LAY-040")
    assert not warn.is_error()
    assert "overlap" in warn.message.lower()


# -------------------------------------------------- Phase 2: expressions in constraint values
def test_expression_in_constraint_is_evaluated(tmp_path: Path) -> None:
    """Phase 2 (DX-1 follow-up): a '{{ }}' expression inside a constraint value is evaluated
    before the anchor is parsed, so it no longer trips ARC-LAY-012."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 400px, height: 400px, dpi: 96}}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "hi"
      style: {font: Inter, font_size: 12px, color: white}
      constraints:
        anchor: {top: parent.top, left: "parent.left + {{ 30 + 10 }}px"}
        size: {w: fill, h: fit_content}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert not any(d.code == "ARC-LAY-012" for d in result.diagnostics), result.diagnostics
    assert result.document is not None
    node = result.document.root.children[0]
    # 40px @ 96 dpi -> 30pt offset baked into the resolved parent-left anchor.
    assert node.constraints.anchors["left"].offset_pt == 30.0


# ------------------------------------------------------------- DX-4: aggregate TPL-014
def test_undeclared_references_aggregate(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 400px, height: 400px, dpi: 96}}}
root:
  type: group
  id: root
  children:
    - id: a
      type: text
      text: "{{ alpha }}"
      style: {font_size: 12px, color: white}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
    - id: b
      type: text
      text: "{{ beta }}"
      style: {font_size: 12px, color: white}
      constraints:
        anchor: {top: parent.center_y, left: parent.left}
        size: {w: fill, h: fit_content}
    - id: c
      type: text
      text: "{{ gamma }}"
      style: {font_size: 12px, color: white}
      constraints:
        anchor: {bottom: parent.bottom, left: parent.left}
        size: {w: fill, h: fit_content}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    refs = [d for d in result.diagnostics if d.code == "ARC-TPL-014"]
    joined = " ".join(d.message for d in refs)
    # All three undeclared references surface in one pass, not one check/fix cycle at a time.
    assert "alpha" in joined and "beta" in joined and "gamma" in joined
    assert len(refs) == 3


# ----------------------------------------------------------- DX-5: locale value validation
def test_locale_bad_values_located(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        "version: 0.1.0\n"
        "locales:\n"
        "  fa: {direction: sideways, digits: klingon, bogus: 1}\n"
        "formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root: {type: group, id: root, children: []}\n",
    )
    result = Compiler().compile(template, None, "square", None, None)
    tpl099 = [d for d in result.diagnostics if d.code == "ARC-TPL-099"]
    assert len(tpl099) >= 3  # direction, digits, and the unknown key
    assert all(d.source is not None and d.source.line is not None for d in tpl099)


def test_locale_good_values_accepted(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        "version: 0.1.0\n"
        "locales:\n"
        "  fa: {direction: rtl, digits: fa, fonts: {body: [Vazirmatn]}}\n"
        "formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root: {type: group, id: root, children: []}\n",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert "ARC-TPL-099" not in _codes(result)


# ----------------------------------------------------------------- DX-10: did-you-mean
def test_did_you_mean_for_typo(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
variables: {title: {type: string, required: false}}
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "{{ titel }}"
      style: {font_size: 12px, color: white}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-014")
    assert diag.hint is not None and "did you mean 'title'" in diag.hint.lower()


# ------------------------------------------------------------ CR-1: default output naming
def test_default_output_reported_on_render_failure(tmp_path: Path) -> None:
    """A render-stage failure (undecodable asset) still reports the resolved output name."""
    facade = build_facade()
    (tmp_path / "broken.png").write_bytes(b"not a real png")
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
root:
  type: group
  id: root
  children:
    - id: pic
      type: image
      asset: broken.png
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 50px, h: 50px}}
""",
    )
    result = facade.render_file(template, None, "square")  # no -o
    assert not result.ok
    # CR-4: the stem is the template directory name when the file is template.yaml.
    assert result.inferred.get("output") == f"{tmp_path.name}.square.png"


def test_default_output_on_compile_error(tmp_path: Path) -> None:
    facade = build_facade()
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "{{ missing }}"
      style: {font_size: 12px, color: white}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
""",
    )
    result = facade.render_file(template, None, "square")
    assert not result.ok
    assert result.inferred.get("output") == f"{tmp_path.name}.square.png"


# ------------------------------------------------- CR-4: path equivalence (dir vs file)
def test_preview_path_dir_and_file_equal() -> None:
    facade = build_facade()
    dir_path = _HELLO
    file_path = _HELLO / "template.yaml"
    assert facade.preview_path(dir_path, "square") == facade.preview_path(file_path, "square")


def test_default_output_stem_dir_and_file_equal() -> None:
    facade = build_facade()
    assert (
        facade._default_output_path(_HELLO, "square")
        == facade._default_output_path(_HELLO / "template.yaml", "square")
        == Path("hello-poster.square.png")
    )


# ------------------------------------------------------- CR-6 / DX-3 / CR-11: inspect
def test_inspect_reflects_compile_failure(tmp_path: Path) -> None:
    facade = build_facade()
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "{{ missing }}"
      style: {font_size: 12px, color: white}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
""",
    )
    report = facade.inspect_template(template)
    assert report.ok is False
    assert report.compiled is False
    assert any(d.code == "ARC-TPL-014" for d in report.diagnostics)


def test_inspect_reports_authored_structural_nodes(tmp_path: Path) -> None:
    facade = build_facade()
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats: {square: {canvas: {width: 400px, height: 400px, dpi: 96}}}
preview_data: {rows: [1]}
root:
  type: group
  id: root
  children:
    - repeat: "{{ rows }}"
      as: r
      key: "{{ loop.index }}"
      node:
        id: row
        type: text
        text: "{{ r }}"
        style: {font_size: 12px, color: white}
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
    - if: "{{ badge is not none }}"
      node:
        id: badge
        type: text
        text: "x"
        style: {font_size: 12px, color: white}
        constraints:
          anchor: {bottom: parent.bottom, left: parent.left}
          size: {w: fill, h: fit_content}
""",
    )
    report = facade.inspect_template(template)
    by_id = {n.id: n for n in report.nodes}
    # The repeat node appears once (authored, not expanded) with its origin + collection.
    assert by_id["row"].origin == "repeat"
    assert by_id["row"].collection == "{{ rows }}"
    assert by_id["row"].loop_var == "r"
    assert "row[0]" not in by_id  # not expanded in the contract view
    assert by_id["badge"].origin == "if"
    assert by_id["badge"].condition == "{{ badge is not none }}"


def test_inspect_distinguishes_no_default_from_null_default(tmp_path: Path) -> None:
    facade = build_facade()
    template = _write(
        tmp_path,
        "version: 0.1.0\n"
        "variables:\n"
        "  a: {type: string, required: false}\n"
        "  b: {type: string, default: null}\n"
        "formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}\n"
        "root: {type: group, id: root, children: []}\n",
    )
    report = facade.inspect_template(template)
    by_name = {v.name: v for v in report.variables}
    assert by_name["a"].has_default is False
    assert by_name["b"].has_default is True


def test_inspect_reports_authored_units(tmp_path: Path) -> None:
    """DX-7: inspect echoes the authored size string alongside the internal points."""
    facade = build_facade()
    report = facade.inspect_template(_HELLO)
    square = next(f for f in report.formats if f.name == "square")
    assert square.width == "1080px"
    assert square.width_pt == pytest.approx(810.0)  # 1080px @ 96dpi

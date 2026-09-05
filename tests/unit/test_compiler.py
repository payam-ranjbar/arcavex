"""Compiler tests: successful compile and located diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.kernel.diagnostics import has_errors
from arcavex.kernel.ir.models import CompiledGroup, CompiledShape, CompiledText
from arcavex.services.template.compiler import Compiler

BASIC = """
version: 0.1.0
variables:
  headline: {type: string, required: true}
formats:
  square: {canvas: {width: 400px, height: 400px, dpi: 96}}
preview_data:
  headline: "Preview"
root:
  type: group
  id: root
  children:
    - id: bg
      type: shape
      shape: rect
      style: {fill: "#112233"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
    - id: title
      type: text
      text: "{{ headline }}"
      style: {font: Inter, font_size: 24px, color: white, align: center}
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 80%, h: fit_content}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "template.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_compile_basic(tmp_path: Path) -> None:
    template = _write(tmp_path, BASIC)
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None
    assert not any(d.is_error() for d in result.diagnostics)
    doc = result.document
    assert doc.canvas.width_pt == 300.0  # 400px @ 96dpi -> 300pt
    assert doc.canvas.dpi == 96
    assert isinstance(doc.root, CompiledGroup)
    bg, title = doc.root.children
    assert isinstance(bg, CompiledShape)
    assert bg.style.fill == (0x11 / 255, 0x22 / 255, 0x33 / 255, 1.0)
    assert isinstance(title, CompiledText)
    assert title.text == "Preview"


def test_data_overrides_preview(tmp_path: Path) -> None:
    template = _write(tmp_path, BASIC)
    data = tmp_path / "data.yaml"
    data.write_text('headline: "Live"\n', encoding="utf-8")
    result = Compiler().compile(template, data, "square", None, None)
    assert result.document is not None
    title = result.document.root.children[1]
    assert isinstance(title, CompiledText)
    assert title.text == "Live"


def test_missing_required_variable_located(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
variables:
  name: {type: string, required: true}
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children: []
""",
    )
    data = tmp_path / "data.yaml"
    data.write_text("unrelated: 1\n", encoding="utf-8")
    result = Compiler().compile(template, data, "square", None, None)
    assert result.document is None
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-014")
    assert diag.source is not None
    assert diag.source.keypath == "name"
    assert diag.hint is not None


def test_duplicate_id_diagnostic(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: dup
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
    - id: dup
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is None
    assert any(d.code == "ARC-IR-020" for d in result.diagnostics)


def test_duplicate_authored_id_is_validated_once_before_repeat_expansion(
    tmp_path: Path,
) -> None:
    """Distinct rendered repeat IDs must not hide one duplicate authored definition."""
    template = _write(
        tmp_path,
        """version: 0.1.0
variables:
  items: {type: list, default: [{id: alpha}, {id: beta}]}
formats:
  square: {canvas: {width: 100pt, height: 100pt, dpi: 72}}
root:
  id: root
  type: group
  children:
    - repeat: "{{ items }}"
      as: item
      key: "{{ item.id }}"
      node:
        id: card
        type: shape
        shape: rect
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
    - id: card
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
""",
    )

    result = Compiler().compile(template, None, "square", None, None)

    duplicates = [
        diagnostic for diagnostic in result.diagnostics if diagnostic.code == "ARC-IR-020"
    ]
    assert result.document is None
    assert len(duplicates) == 1
    assert duplicates[0].source is not None
    assert duplicates[0].source.keypath == "root.children[1].id"


def test_authored_ids_reject_repeat_brackets_and_reserved_virtual_prefix(
    tmp_path: Path,
) -> None:
    """A real authored node must not impersonate generated instance or virtual IDs."""
    template = _write(
        tmp_path,
        """version: 0.1.0
formats:
  square: {canvas: {width: 100pt, height: 100pt, dpi: 72}}
root:
  id: root
  type: group
  children:
    - {id: "bad[left", type: shape, shape: rect}
    - {id: "bad]right", type: shape, shape: rect}
    - {id: "@arcavex/virtual/pretend", type: shape, shape: rect}
""",
    )

    result = Compiler().compile(template, None, "square", None, None)

    invalid = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "ARC-TPL-030"]
    assert result.document is None
    assert len(invalid) == 3
    assert [diagnostic.source.keypath for diagnostic in invalid if diagnostic.source] == [
        "root.children[0].id",
        "root.children[1].id",
        "root.children[2].id",
    ]


def test_unknown_format(tmp_path: Path) -> None:
    template = _write(tmp_path, BASIC)
    result = Compiler().compile(template, None, "nope", None, None)
    assert any(d.code == "ARC-TPL-022" for d in result.diagnostics)


def test_effects_compile_when_present(tmp_path: Path) -> None:
    """Effects are no longer rejected: an authored effect list compiles into the IR."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: s
      type: shape
      shape: rect
      effects: [{name: blur, params: {radius: 3pt}}]
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
""",
    )
    # A bare compiler has no effect registry, so it accepts the list without enforcing names;
    # the enforcement path (unknown effect / bad params) is covered by the effects test module.
    result = Compiler().compile(template, None, "square", None, None)
    assert not any(d.code == "ARC-FX-900" for d in result.diagnostics)
    assert result.document is not None


def test_list_formats(tmp_path: Path) -> None:
    template = _write(tmp_path, BASIC)
    assert Compiler().list_formats(template) == ["square"]


# --------------------------------------------------------------------- remediation tests
def test_preview_data_does_not_backfill_supplied_data(tmp_path: Path) -> None:
    """CR-1/DX-1: a data file that omits a required var must error even if preview has it."""
    template = _write(tmp_path, BASIC)  # BASIC has preview_data.headline = "Preview"
    data = tmp_path / "data.yaml"
    data.write_text("unrelated: 1\n", encoding="utf-8")
    result = Compiler().compile(template, data, "square", None, None)
    assert result.document is None
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-014")
    assert diag.source is not None and diag.source.keypath == "headline"
    # File/line come from the template declaration, not the data file (CR-6/DX-8).
    assert diag.source.file == str(template)
    assert diag.source.line is not None


def test_preview_used_only_without_data_reports_inference(tmp_path: Path) -> None:
    """DX-7: preview_data is a fallback only when --data is omitted, and it is reported."""
    template = _write(tmp_path, BASIC)
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None
    assert result.inferred.get("data") == "preview_data"


def test_format_inference_reported(tmp_path: Path) -> None:
    template = _write(tmp_path, BASIC)
    result = Compiler().compile(template, None, None, None, None)
    assert result.inferred.get("format") == "square"
    assert result.format_name == "square"


def _nongoal_template(tmp_path: Path, extra: str) -> Path:
    return _write(
        tmp_path,
        "version: 0.1.0\n"
        + extra
        + "formats:\n  square: {canvas: {width: 100px, height: 100px, dpi: 96}}\n"
        "root: {type: group, id: root, children: []}\n",
    )


def test_locales_section_shape_accepted(tmp_path: Path) -> None:
    """Scope item 1: a well-formed locales section is parsed, not rejected (Phase 1)."""
    template = _nongoal_template(
        tmp_path, "locales:\n  en: {direction: ltr}\n  fa: {direction: rtl}\n"
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None
    assert not any(d.is_error() for d in result.diagnostics)


def test_locales_malformed_shape_rejected(tmp_path: Path) -> None:
    """A locales section that is not a mapping of mappings is a located error."""
    template = _nongoal_template(tmp_path, "locales:\n  en: not-a-mapping\n")
    result = Compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-TPL-098" for d in result.diagnostics)


def test_requesting_declared_locale_applies(tmp_path: Path) -> None:
    """Phase 2: a declared --locale is applied (no ARC-TPL-091 deferral) and compiles."""
    template = _nongoal_template(tmp_path, "locales:\n  fa: {direction: rtl}\n")
    result = Compiler().compile(template, None, "square", "fa", None)
    assert not has_errors(result.diagnostics), result.diagnostics
    assert result.document is not None
    assert result.document.root.direction == "rtl"


def test_requesting_undeclared_locale_is_error(tmp_path: Path) -> None:
    """A locale the template does not declare is a located error (ARC-TPL-100)."""
    template = _nongoal_template(tmp_path, "locales:\n  fa: {direction: rtl}\n")
    result = Compiler().compile(template, None, "square", "de", None)
    assert any(d.code == "ARC-TPL-100" for d in result.diagnostics)


def test_nongoal_styles_section_rejected(tmp_path: Path) -> None:
    template = _nongoal_template(tmp_path, "styles:\n  pop: {}\n")
    result = Compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-TPL-093" for d in result.diagnostics)


def test_format_patch_applies(tmp_path: Path) -> None:
    """Phase 2: a per-format patch is applied to the authored AST (no ARC-TPL-095)."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats:
  square:
    canvas: {width: 100px, height: 100px, dpi: 96}
    patch:
      - set: nodes.box.style.opacity
        value: 0.5
root:
  type: group
  id: root
  children:
    - id: box
      type: shape
      shape: rect
      style: {fill: "#ffffff", opacity: 1.0}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 50px, h: 50px}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert not has_errors(result.diagnostics), result.diagnostics
    assert result.document is not None
    box = result.document.root.children[0]
    assert box.style.opacity == 0.5


def test_missing_asset_located_compile_error(tmp_path: Path) -> None:
    """CR-3/DX-4: a missing image asset is caught at compile time with a located ARC-AST."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: pic
      type: image
      asset: does-not-exist.png
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 50px, h: 50px}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-AST-001")
    assert diag.source is not None and diag.source.keypath == "root.children[0].asset"
    assert "does-not-exist.png" in diag.message  # template-relative, not absolute


def test_under_constrained_missing_size(tmp_path: Path) -> None:
    """DX-2: a node with anchors but no size is under-constrained, not silently filled."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: label
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-LAY-032" for d in result.diagnostics)


def test_bare_canvas_dim_ok_and_bad_dpi_located(tmp_path: Path) -> None:
    """DX-3: bare-number canvas dims parse as px; a malformed dpi is a located ARC-IR."""
    ok = _write(
        tmp_path,
        "version: 0.1.0\nformats:\n  square: {canvas: {width: 800, height: 400px, dpi: 96}}\n"
        "root: {type: group, id: root, children: []}\n",
    )
    result = Compiler().compile(ok, None, "square", None, None)
    assert result.document is not None
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: 0.1.0\nformats:\n  square: {canvas: {width: 800px, height: 400px, dpi: abc}}\n"
        "root: {type: group, id: root, children: []}\n",
        encoding="utf-8",
    )
    result = Compiler().compile(bad, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-IR-014")
    assert diag.source is not None and diag.source.keypath == "formats.square.canvas.dpi"


def test_budget_exhaustion_distinct_code(tmp_path: Path) -> None:
    """CR-5: an over-budget expression yields the budget code, not a syntax error."""
    expr = "{{ " + "1" + " + 1" * 5000 + " }}"
    template = _write(
        tmp_path,
        "version: 0.1.0\n"
        "variables: {t: {type: string, required: false}}\n"
        "formats:\n  square: {canvas: {width: 100px, height: 100px, dpi: 96}}\n"
        "root:\n"
        "  type: group\n"
        "  id: root\n"
        "  children:\n"
        "    - id: t\n"
        "      type: text\n"
        f"      text: \"{expr}\"\n"
        "      style: {font_size: 10px}\n"
        "      constraints:\n"
        "        anchor: {top: parent.top, left: parent.left}\n"
        "        size: {w: fill, h: fit_content}\n",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-TPL-062" for d in result.diagnostics)


def test_line_height_rejected(tmp_path: Path) -> None:
    """CR-9: line_height is rejected (not silently ignored) given the text-stack limits."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "hi"
      style: {font_size: 10px, line_height: 1.5}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert any(d.code == "ARC-TPL-053" for d in result.diagnostics)


def test_unknown_font_family_located_exit3_code(tmp_path: Path) -> None:
    """DX-5: a font absent from the DB fails compilation with the missing-font code."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "hi"
      style: {font: ComicNeueSans, font_size: 10px}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
""",
    )
    result = Compiler(frozenset({"Inter"})).compile(template, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-RND-010")
    assert "ComicNeueSans" in diag.message
    assert diag.source is not None and diag.source.keypath == "root.children[0].style.font"


def test_variable_type_mismatch_reported(tmp_path: Path) -> None:
    """CR-21: a supplied value of the wrong declared type is reported."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
variables:
  count: {type: number, required: true}
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root: {type: group, id: root, children: []}
""",
    )
    data = tmp_path / "data.yaml"
    data.write_text('count: "not a number"\n', encoding="utf-8")
    result = Compiler().compile(template, data, "square", None, None)
    assert any(d.code == "ARC-TPL-015" for d in result.diagnostics)


def test_list_rooted_data_file_rejected(tmp_path: Path) -> None:
    """CR-21: a data file whose root is a list is a located error, not silently ignored."""
    template = _write(tmp_path, BASIC)
    data = tmp_path / "data.yaml"
    data.write_text("- 1\n- 2\n", encoding="utf-8")
    result = Compiler().compile(template, data, "square", None, None)
    assert any(d.code == "ARC-TPL-012" for d in result.diagnostics)


# ------------------------------------------------------------- basis-free lengths refuse '%'
_PERCENT_NODE = """
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: n
      type: %(kind)s
%(body)s
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 100px, h: 100px}
"""


def _percent_diag(tmp_path: Path, kind: str, body: str):  # noqa: ANN202
    template = _write(tmp_path, _PERCENT_NODE % {"kind": kind, "body": body})
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is None
    diag = next(d for d in result.diagnostics if d.is_error())
    assert diag.code == "ARC-IR-011", diag.model_dump()
    assert diag.source is not None
    assert "px" in (diag.hint or "") and "pt" in (diag.hint or "") and "mm" in (diag.hint or "")
    return diag


@pytest.mark.parametrize("field", ["stroke_width", "corner_radius", "letter_spacing", "font_size"])
def test_percentage_style_length_is_a_located_error(tmp_path: Path, field: str) -> None:
    """A style length has no parent basis, so '5%' is refused at validation, not at render."""
    diag = _percent_diag(tmp_path, "shape", f"      style: {{fill: '#FF0000', {field}: 5%}}")
    assert diag.source is not None
    assert diag.source.keypath == f"root.children[0].style.{field}"
    assert diag.source.line == 11


def test_percentage_run_override_is_a_located_error(tmp_path: Path) -> None:
    diag = _percent_diag(
        tmp_path, "text", "      runs:\n        - {text: hi, font_size: 50%}"
    )
    assert diag.source is not None and diag.source.keypath == "root.children[0].runs[0].font_size"


def test_percentage_fit_min_size_is_a_located_error(tmp_path: Path) -> None:
    diag = _percent_diag(
        tmp_path, "text", "      text: hi\n      fit: {policy: shrink_to_fit, min_size: 50%}"
    )
    assert diag.source is not None and diag.source.keypath == "root.children[0].fit.min_size"


@pytest.mark.parametrize(
    ("body", "keypath"),
    [
        ("      layout: vstack\n      gap: 5%", "root.children[0].gap"),
        ("      layout: vstack\n      padding: 5%", "root.children[0].padding"),
        ("      layout: vstack\n      padding: {top: 5%}", "root.children[0].padding.top"),
    ],
)
def test_percentage_stack_spacing_is_a_located_error(
    tmp_path: Path, body: str, keypath: str
) -> None:
    diag = _percent_diag(tmp_path, "group", body)
    assert diag.source is not None and diag.source.keypath == keypath


def test_percentage_size_clamp_is_a_located_error(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        (_PERCENT_NODE % {"kind": "shape", "body": "      style: {fill: '#FF0000'}"}).replace(
            "size: {w: 100px, h: 100px}", "size: {w: {value: 50%, min: 10%}, h: 100px}"
        ),
    )
    result = Compiler().compile(template, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.is_error())
    assert diag.code == "ARC-IR-011"
    assert diag.source is not None
    assert diag.source.keypath == "root.children[0].constraints.size.w.min"


def test_percentage_canvas_dimension_is_a_located_error(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        "version: 0.1.0\nformats:\n  square: {canvas: {width: 50%, height: 400px, dpi: 96}}\n"
        "root: {type: group, id: root, children: []}\n",
    )
    result = Compiler().compile(template, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.is_error())
    assert diag.code == "ARC-IR-011"
    assert diag.source is not None and diag.source.keypath == "formats.square.canvas.width"


# --------------------------------------------------------------------- italic is a boolean
def _style_diag(tmp_path: Path, style: str, code: str):  # noqa: ANN202
    template = _write(
        tmp_path, _PERCENT_NODE % {"kind": "text", "body": f"      text: hi\n      style: {style}"}
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is None
    diag = next(d for d in result.diagnostics if d.is_error())
    assert diag.code == code, diag.model_dump()
    assert diag.source is not None
    return diag


@pytest.mark.parametrize("value", ['"no"', '"false"', '"yes"', "1", "0"])
def test_italic_must_be_a_yaml_boolean(tmp_path: Path, value: str) -> None:
    """A quoted word (or a number) was coerced with bool(), so `italic: "no"` rendered italic."""
    diag = _style_diag(tmp_path, f"{{italic: {value}}}", "ARC-IR-014")
    assert diag.source is not None
    assert diag.source.keypath == "root.children[0].style.italic"
    assert diag.source.line == 12
    assert "boolean" in diag.message
    assert "true or false" in (diag.hint or "")


def test_run_italic_must_be_a_yaml_boolean(tmp_path: Path) -> None:
    template = _write(
        tmp_path,
        _PERCENT_NODE % {"kind": "text", "body": '      runs:\n        - {text: hi, italic: "no"}'},
    )
    result = Compiler().compile(template, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.is_error())
    assert diag.code == "ARC-IR-014"
    assert diag.source is not None and diag.source.keypath == "root.children[0].runs[0].italic"


@pytest.mark.parametrize(("value", "expected"), [("true", True), ("false", False)])
def test_italic_accepts_real_booleans(tmp_path: Path, value: str, expected: bool) -> None:
    body = f"      text: hi\n      style: {{italic: {value}}}"
    template = _write(tmp_path, _PERCENT_NODE % {"kind": "text", "body": body})
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None, [d.model_dump() for d in result.diagnostics]
    assert result.document.root.children[0].style.italic is expected


# ------------------------------------------------------------------- opacity stays in 0..1
@pytest.mark.parametrize("value", ["1.5", "-0.1", "2", ".nan"])
def test_opacity_outside_the_unit_interval_is_a_located_error(tmp_path: Path, value: str) -> None:
    """`opacity: 1.5` validated and rendered opaque; the range is now checked at validation."""
    diag = _style_diag(tmp_path, f"{{opacity: {value}}}", "ARC-IR-014")
    assert diag.source is not None
    assert diag.source.keypath == "root.children[0].style.opacity"
    assert diag.source.line == 12
    assert "0 to 1" in diag.message


@pytest.mark.parametrize("value", ["0", "1", "0.5", "1.0"])
def test_opacity_accepts_the_closed_unit_interval(tmp_path: Path, value: str) -> None:
    template = _write(
        tmp_path,
        _PERCENT_NODE % {"kind": "shape", "body": f"      style: {{fill: red, opacity: {value}}}"},
    )
    result = Compiler().compile(template, None, "square", None, None)
    assert result.document is not None, [d.model_dump() for d in result.diagnostics]
    assert result.document.root.children[0].style.opacity == float(value)


def test_missing_size_hint_names_the_span_and_inset_idioms(tmp_path: Path) -> None:
    """ARC-LAY-032 says how to reach both edges, so an author does not reach for two anchors."""
    template = _write(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: frame
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
    - id: bar
      type: shape
      shape: rect
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {h: 10px}
""",
    )
    result = Compiler().compile(template, None, "square", None, None)
    whole = next(d for d in result.diagnostics if d.code == "ARC-LAY-032")
    assert whole.hint is not None and "'fill'" in whole.hint and "vstack" in whole.hint
    # The per-axis form is reached once the first node is fixed.
    fixed = template.read_text(encoding="utf-8").replace(
        "        anchor: {top: parent.top, left: parent.left}\n    - id: bar",
        "        anchor: {top: parent.top, left: parent.left}\n        size: {w: fill, h: fill}"
        "\n    - id: bar",
    )
    template.write_text(fixed, encoding="utf-8")
    result = Compiler().compile(template, None, "square", None, None)
    axis = next(d for d in result.diagnostics if d.code == "ARC-LAY-032")
    assert axis.source is not None and axis.source.keypath is not None
    assert axis.source.keypath.endswith("constraints.size.w")
    assert axis.hint is not None and "'fill'" in axis.hint and "inset" in axis.hint

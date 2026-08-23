"""Locale system tests: data-overlay merge, digits, direction, and font overrides."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml.comments import TaggedScalar
from ruamel.yaml.tag import Tag

from arcavex.services.template.compiler import Compiler
from arcavex.services.template.overlays import merge_overlay


def _delete_marker() -> TaggedScalar:
    """A YAML ``!delete`` tagged scalar, as the loader produces for ``key: !delete``."""
    return TaggedScalar(value="", style=None, tag=Tag(suffix="!delete"))


# ------------------------------------------------------------ overlay merge semantics
def test_mapping_merge_recursive() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    overlay = {"a": {"y": 20, "z": 30}}
    assert merge_overlay(base, overlay) == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3}


def test_scalar_replaces_and_list_replaces_whole() -> None:
    base = {"n": 1, "items": [1, 2, 3]}
    overlay = {"n": 9, "items": [4]}
    assert merge_overlay(base, overlay) == {"n": 9, "items": [4]}


def test_delete_marker_removes_key() -> None:
    # CR-17: only the explicit YAML tag `!delete` removes a key.
    base = {"keep": 1, "drop": 2}
    assert merge_overlay(base, {"drop": _delete_marker()}) == {"keep": 1}


def test_plain_delete_string_is_a_value_not_deletion() -> None:
    # CR-17: the plain string "!delete" is ordinary data, so it stays representable.
    base = {"keep": 1, "note": "old"}
    assert merge_overlay(base, {"note": "!delete"}) == {"keep": 1, "note": "!delete"}


def test_null_is_a_value_not_deletion() -> None:
    base = {"a": 1}
    assert merge_overlay(base, {"a": None}) == {"a": None}


# ------------------------------------------------------------ locale application
_TPL = """
version: 0.1.0
variables:
  hour: {type: number, default: 17}
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
locales:
  en: {direction: ltr}
  fa:
    direction: rtl
    digits: fa
    fonts: {Inter: [Vazirmatn, Inter]}
    data: {hour: 19}
preview_data: {hour: 17}
root:
  type: group
  id: root
  children:
    - id: label
      type: text
      text: "hour {{ hour }}"
      style: {font: Inter, font_size: 20px, color: black}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
"""


def _label(tmp_path: Path, locale: str | None):  # noqa: ANN202
    template = tmp_path / "t.yaml"
    template.write_text(_TPL, encoding="utf-8")
    result = Compiler().compile(template, None, "square", locale, None)
    assert result.document is not None, result.diagnostics
    return result.document, result.document.root.children[0]


def test_locale_direction_sets_root_default(tmp_path: Path) -> None:
    doc, _ = _label(tmp_path, "fa")
    assert doc.root.direction == "rtl"
    doc_en, _ = _label(tmp_path, "en")
    assert doc_en.root.direction == "ltr"


def test_locale_data_overlay_and_fa_digits(tmp_path: Path) -> None:
    _, label = _label(tmp_path, "fa")
    # data overlay set hour=19, and fa digits map it: "hour ۱۹".
    assert "۱۹" in label.text
    assert "19" not in label.text


def test_locale_font_override(tmp_path: Path) -> None:
    _, label = _label(tmp_path, "fa")
    assert label.style.font_families == ("Vazirmatn", "Inter")
    _, en = _label(tmp_path, "en")
    assert en.style.font_families == ("Inter",)


def test_en_locale_keeps_ascii_digits(tmp_path: Path) -> None:
    _, label = _label(tmp_path, "en")
    assert "17" in label.text  # no overlay, no digit mapping


def test_undeclared_locale_is_error(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    template.write_text(_TPL, encoding="utf-8")
    result = Compiler().compile(template, None, "square", "de", None)
    assert any(d.code == "ARC-TPL-100" for d in result.diagnostics)


def test_sibling_data_file_overlay(tmp_path: Path) -> None:
    """--data base.yaml --locale fa auto-applies base.fa.yaml if present (reported inferred)."""
    template = tmp_path / "t.yaml"
    template.write_text(_TPL, encoding="utf-8")
    (tmp_path / "d.yaml").write_text("hour: 8\n", encoding="utf-8")
    (tmp_path / "d.fa.yaml").write_text("hour: 21\n", encoding="utf-8")
    result = Compiler().compile(template, tmp_path / "d.yaml", "square", "fa", None)
    assert result.document is not None, result.diagnostics
    label = result.document.root.children[0]
    assert "۲۱" in label.text  # sibling overlay hour=21, fa digits
    assert result.inferred.get("data_overlay") == "d.fa.yaml"


def test_four_layer_data_precedence(tmp_path: Path) -> None:
    """RR2-1 / ADR-0002 D3: preview < locales.<L>.data < user base --data < user sidecar.

    User data always outranks template data; the sidecar outranks the base file. Each
    variable below is set at a different highest layer so the winner proves the order.
    """
    template = tmp_path / "t.yaml"
    template.write_text(_TPL, encoding="utf-8")
    # hour set at every layer; base wins over inline locale data, sidecar wins over base.
    (tmp_path / "d.yaml").write_text("hour: 8\n", encoding="utf-8")
    result = Compiler().compile(template, tmp_path / "d.yaml", "square", "fa", None)
    assert result.document is not None, result.diagnostics
    label = result.document.root.children[0]
    # No sidecar: user base (8) must beat inline locale data (19).
    assert "۸" in label.text and "۱۹" not in label.text
    # Inline overlay application is reported as an inference (RR2-3).
    assert result.inferred.get("locale_data") == "locales.fa.data"
    # With a sidecar, it outranks the base file.
    (tmp_path / "d.fa.yaml").write_text("hour: 21\n", encoding="utf-8")
    result2 = Compiler().compile(template, tmp_path / "d.yaml", "square", "fa", None)
    assert result2.document is not None, result2.diagnostics
    assert "۲۱" in result2.document.root.children[0].text
    # Without user data at all, inline locale data (19) beats preview_data (17).
    result3 = Compiler().compile(template, None, "square", "fa", None)
    assert result3.document is not None, result3.diagnostics
    assert "۱۹" in result3.document.root.children[0].text


# --------------------------------------------- rendering a locale with no locale content


_RTL_ONLY_TPL = """\
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
locales:
  en: {direction: ltr}
  fa: {direction: rtl, digits: fa}
preview_data: {when: "6:00-8:30 PM"}
root:
  type: group
  id: root
  children:
    - id: label
      type: text
      text: "{{ when }}"
      style: {font: Inter, font_size: 20px, color: black}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
"""


def test_a_locale_with_no_content_of_its_own_says_so(tmp_path: Path) -> None:
    """Rendering `--locale fa` over English content is the quietest way to ship a wrong poster.

    The locale's direction is applied to whatever text is there, so an English time range comes
    out bidi-reordered as "PM 8:30-6:00" and a date as "SEP 2026 24". The picture looks entirely
    normal -- correct fonts, no overflow, nothing to notice at thumbnail size -- and states the
    wrong time. A tester rendered exactly this and read it as an engine bug.

    Applying the locale is right; doing it silently is not. When neither an inline
    `locales.<L>.data` nor a sibling `<base>.<locale>.yaml` supplied any content for a locale
    whose direction differs from the source, the engine says so.
    """
    template = tmp_path / "t.yaml"
    template.write_text(_RTL_ONLY_TPL, encoding="utf-8")

    result = Compiler().compile(template, None, "square", "fa", None)

    assert result.document is not None, result.diagnostics
    warned = [d for d in result.diagnostics if d.code == "ARC-TPL-102"]
    assert warned, [d.code for d in result.diagnostics]
    assert warned[0].severity == "warning"
    assert "fa" in warned[0].message


def test_no_warning_when_the_locale_brings_its_own_content(tmp_path: Path) -> None:
    """The template above but with inline locale data: nothing to warn about."""
    template = tmp_path / "t.yaml"
    template.write_text(
        _RTL_ONLY_TPL.replace(
            "  fa: {direction: rtl, digits: fa}",
            '  fa: {direction: rtl, digits: fa, data: {when: "۱۸:۰۰ تا ۲۰:۳۰"}}',
        ),
        encoding="utf-8",
    )

    result = Compiler().compile(template, None, "square", "fa", None)

    assert not [d for d in result.diagnostics if d.code == "ARC-TPL-102"]


def test_no_warning_for_a_locale_that_reads_the_same_direction(tmp_path: Path) -> None:
    """`--locale en` on English content is exactly what it looks like."""
    template = tmp_path / "t.yaml"
    template.write_text(_RTL_ONLY_TPL, encoding="utf-8")

    result = Compiler().compile(template, None, "square", "en", None)

    assert not [d for d in result.diagnostics if d.code == "ARC-TPL-102"]


_SHADOW_TPL = """\
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
variables: {loc: {type: string, required: false}}
locales:
  en: {direction: ltr, data: {loc: en}}
  fa: {direction: rtl, data: {loc: fa}}
preview_data: {}
root:
  type: group
  id: root
  children:
    - id: label
      type: text
      text: "{{ loc }}"
      style: {font: Inter, font_size: 20px, color: black}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fit_content}}
"""


def test_a_data_file_that_shadows_locale_content_says_so(tmp_path: Path) -> None:
    """Project data outranking template locale data is by design; doing it in silence is not.

    A template shipping `locales.fa.data` and a project data file that also sets the same key
    produced a perfectly mirrored right-to-left layout containing entirely English copy. It
    validated, it rendered, and it looked deliberate — the worst shape a failure can take.
    """
    template = tmp_path / "t.yaml"
    template.write_text(_SHADOW_TPL, encoding="utf-8")
    data = tmp_path / "data.yaml"
    data.write_text("loc: en\n", encoding="utf-8")

    result = Compiler().compile(template, data, "square", "fa", None)

    shadowed = [d for d in result.diagnostics if d.code == "ARC-TPL-103"]
    assert shadowed, [d.code for d in result.diagnostics]
    assert shadowed[0].severity == "warning"
    assert "loc" in shadowed[0].message
    assert "fa" in shadowed[0].message


def test_no_warning_when_the_data_file_leaves_locale_content_alone(tmp_path: Path) -> None:
    """A data file that does not touch the locale's keys shadows nothing."""
    template = tmp_path / "t.yaml"
    template.write_text(_SHADOW_TPL, encoding="utf-8")
    data = tmp_path / "data.yaml"
    data.write_text("unrelated: 1\n", encoding="utf-8")

    result = Compiler().compile(template, data, "square", "fa", None)

    assert not [d for d in result.diagnostics if d.code == "ARC-TPL-103"]


def test_paint_on_a_group_is_reported_rather_than_ignored(tmp_path: Path) -> None:
    """A known field that silently does nothing is worse than an unknown one that errors.

    `style` is shared vocabulary, so a group setting `fill` and `corner_radius` passed every
    check and rendered exactly as if the keys were absent. A designer building a badge that way
    only found out by looking at the pixels.
    """
    template = tmp_path / "t.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {square: {canvas: {width: 200px, height: 200px, dpi: 72}}}\n"
        "preview_data: {}\n"
        "root:\n"
        "  type: group\n"
        "  id: root\n"
        "  children:\n"
        "    - id: badge\n"
        "      type: group\n"
        '      style: {fill: "#FF4A1C", corner_radius: 2pt}\n'
        "      constraints:\n"
        "        anchor: {top: parent.top, left: parent.left}\n"
        "        size: {w: 50px, h: 20px}\n"
        "      children: []\n",
        encoding="utf-8",
    )

    result = Compiler().compile(template, None, "square", None, None)

    warned = [d for d in result.diagnostics if d.code == "ARC-TPL-104"]
    assert warned, [d.code for d in result.diagnostics]
    assert warned[0].severity == "warning"
    assert "fill" in warned[0].message and "corner_radius" in warned[0].message


def test_paint_on_a_shape_is_exactly_what_it_looks_like(tmp_path: Path) -> None:
    """The same fields on a shape are the ordinary case and must stay quiet."""
    template = tmp_path / "t.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {square: {canvas: {width: 200px, height: 200px, dpi: 72}}}\n"
        "preview_data: {}\n"
        "root:\n"
        "  type: group\n"
        "  id: root\n"
        "  children:\n"
        "    - id: plate\n"
        "      type: shape\n"
        "      shape: rect\n"
        '      style: {fill: "#FF4A1C", corner_radius: 2pt}\n'
        "      constraints:\n"
        "        anchor: {top: parent.top, left: parent.left}\n"
        "        size: {w: 50px, h: 20px}\n",
        encoding="utf-8",
    )

    result = Compiler().compile(template, None, "square", None, None)

    assert not [d for d in result.diagnostics if d.code == "ARC-TPL-104"]


def test_the_size_hint_does_not_offer_text_only_sizing_to_a_group(tmp_path: Path) -> None:
    """Two hints must not send an author round a loop.

    The missing-size error suggested `fit_content` for any node, and using it produced "Only
    text nodes support fit_content" from the very next check. A designer following both built a
    spreadsheet of hand-computed heights instead.
    """
    template = tmp_path / "t.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {square: {canvas: {width: 200px, height: 200px, dpi: 72}}}\n"
        "preview_data: {}\n"
        "root:\n"
        "  type: group\n"
        "  id: root\n"
        "  children:\n"
        "    - id: stack\n"
        "      type: group\n"
        "      constraints:\n"
        "        anchor: {top: parent.top, left: parent.left}\n"
        "        size: {w: fill}\n"
        "      children: []\n",
        encoding="utf-8",
    )

    result = Compiler().compile(template, None, "square", None, None)

    missing = [d for d in result.diagnostics if d.code == "ARC-LAY-032"]
    assert missing, [d.code for d in result.diagnostics]
    assert "fit_content is text-only" in (missing[0].hint or "")


def test_a_text_node_is_still_told_about_fit_content(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {square: {canvas: {width: 200px, height: 200px, dpi: 72}}}\n"
        "preview_data: {}\n"
        "root:\n"
        "  type: group\n"
        "  id: root\n"
        "  children:\n"
        "    - id: line\n"
        "      type: text\n"
        '      text: "hi"\n'
        "      style: {font: Inter, font_size: 20px, color: black}\n"
        "      constraints:\n"
        "        anchor: {top: parent.top, left: parent.left}\n"
        "        size: {w: fill}\n",
        encoding="utf-8",
    )

    result = Compiler().compile(template, None, "square", None, None)

    missing = [d for d in result.diagnostics if d.code == "ARC-LAY-032"]
    assert missing
    assert "'fit_content'" in (missing[0].hint or "")


_COMBO_TPL = """\
version: 0.1.0
formats:
  poster:
    canvas: {width: 400px, height: 600px, dpi: 72}
    patch:
      - set: "nodes.title.style.font_size"
        value: 132px
  square:
    canvas: {width: 200px, height: 200px, dpi: 72}
locales:
  en: {direction: ltr}
  fa:
    direction: rtl
    patch:
      - set: "nodes.title.style.letter_spacing"
        value: 0px
    formats:
      poster:
        patch:
          - set: "nodes.title.style.font_size"
            value: 96px
preview_data: {}
root:
  type: group
  id: root
  children:
    - id: title
      type: text
      text: "hello"
      style: {font: Inter, font_size: 40px, color: black, letter_spacing: 2px}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
"""


def _title_size(tmp_path: Path, fmt: str, locale: str) -> float:
    template = tmp_path / "t.yaml"
    template.write_text(_COMBO_TPL, encoding="utf-8")
    result = Compiler().compile(template, None, fmt, locale, None)
    assert result.document is not None, [d.model_dump() for d in result.diagnostics]
    return result.document.root.children[0].style.font_size_pt


def test_a_locale_can_patch_one_format_without_touching_the_others(tmp_path: Path) -> None:
    """"Farsi, on the poster" was not expressible, and every bilingual campaign needs it.

    Patch order is format then locale, so a single `locales.fa.patch` overriding a size flattened
    the poster's 132px display down to whatever the square wanted. Scripts differ in optical size
    at every format, so the workaround was duplicating the node in the tree and gating both
    copies on the locale.
    """
    assert _title_size(tmp_path, "poster", "en") == 132.0
    assert _title_size(tmp_path, "square", "en") == 40.0

    # Farsi on the poster takes the combined patch; Farsi on the square keeps the square's size.
    assert _title_size(tmp_path, "poster", "fa") == 96.0
    assert _title_size(tmp_path, "square", "fa") == 40.0


def test_the_locale_patch_still_applies_to_every_format(tmp_path: Path) -> None:
    """The plain locale patch is unchanged: it is the "all formats" layer."""
    template = tmp_path / "t.yaml"
    template.write_text(_COMBO_TPL, encoding="utf-8")

    for fmt in ("poster", "square"):
        result = Compiler().compile(template, None, fmt, "fa", None)
        assert result.document is not None
        assert result.document.root.children[0].style.letter_spacing_pt == 0.0


# ---------------------------------------------------- patch paths that address list items


def _patched(ops: list[dict[str, object]]) -> dict:
    """Run patch ops against a small node tree and return it."""
    from arcavex.services.template.overlays import PatchLog, apply_patches

    root = {
        "type": "group",
        "id": "root",
        "children": [
            {
                "id": "title",
                "type": "text",
                "text": "hello",
                "effects": [
                    {"name": "blur", "params": {"radius": "8px"}},
                    {"name": "grain", "params": {"amount": 0.1}},
                ],
            }
        ],
    }
    apply_patches(root, ops, "test", Path("t.yaml"), "test.patch", PatchLog())
    return root["children"][0]


def test_a_patch_can_address_one_item_in_a_list() -> None:
    """Tuning one effect parameter should not mean replacing the whole effects list.

    Patch paths walked mappings only, so `nodes.title.effects.0.params.radius` was rejected as
    an "unknown patch path segment '0'". The workaround — rewriting the entire list per locale —
    clobbered the per-format values that same list carried.
    """
    node = _patched([{"set": "nodes.title.effects.0.params.radius", "value": "2px"}])

    assert node["effects"][0]["params"]["radius"] == "2px"
    # The neighbour is untouched, which is the whole point of addressing one item.
    assert node["effects"][1] == {"name": "grain", "params": {"amount": 0.1}}


def test_a_list_item_can_be_removed_by_index() -> None:
    node = _patched([{"remove": "nodes.title.effects.0"}])

    assert [effect["name"] for effect in node["effects"]] == ["grain"]


def test_an_index_past_the_end_is_refused_with_the_length() -> None:
    from arcavex.kernel.diagnostics import DiagnosticError

    with pytest.raises(DiagnosticError) as raised:
        _patched([{"set": "nodes.title.effects.7.params.radius", "value": "2px"}])

    message = " ".join(d.message for d in raised.value.diagnostics)
    assert "out of range" in message and "2" in message


def test_a_word_where_a_list_index_belongs_says_so() -> None:
    from arcavex.kernel.diagnostics import DiagnosticError

    with pytest.raises(DiagnosticError) as raised:
        _patched([{"set": "nodes.title.effects.first.params.radius", "value": "2px"}])

    message = " ".join(d.message for d in raised.value.diagnostics)
    assert "must be an index" in message


_DIGITS_TPL = """\
version: 0.1.0
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
variables:
  clock: {type: string, required: false}
  count: {type: number, required: false}
locales:
  en: {direction: ltr, digits: en}
  fa: {direction: rtl, digits: fa}
preview_data: {clock: "20:00", count: 6}
root:
  type: group
  id: root
  children:
    - id: time
      type: text
      text: "{{ clock }}"
      style: {font: Inter, font_size: 20px, color: black}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
    - id: remaining
      type: text
      text: "{{ count }}"
      style: {font: Inter, font_size: 20px, color: black}
      constraints:
        anchor: {top: parent.top+30px, left: parent.left}
        size: {w: fill, h: fit_content}
"""


def test_locale_digits_reach_digits_inside_a_string(tmp_path: Path) -> None:
    """One render should not mix numbering systems.

    `digits: fa` converted numeric values only, so a count rendered as ۶ while a clock time
    carried in a string stayed "20:00" — in the same poster, with nothing saying why. Every
    numeric-bearing string had to be passed through `locale_digits` by hand.
    """
    template = tmp_path / "t.yaml"
    template.write_text(_DIGITS_TPL, encoding="utf-8")

    result = Compiler().compile(template, None, "square", "fa", None)

    assert result.document is not None, [d.model_dump() for d in result.diagnostics]
    clock, count = result.document.root.children[0], result.document.root.children[1]
    assert count.text == "۶", count.text
    assert clock.text == "۲۰:۰۰", clock.text


def test_an_ltr_locale_leaves_the_digits_alone(tmp_path: Path) -> None:
    template = tmp_path / "t.yaml"
    template.write_text(_DIGITS_TPL, encoding="utf-8")

    result = Compiler().compile(template, None, "square", "en", None)

    assert result.document is not None
    assert result.document.root.children[0].text == "20:00"

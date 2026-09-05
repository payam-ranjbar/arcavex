"""Template-level patch roots: ``formats``, ``variables``, ``preview_data``, ``locales``, ``style``.

An assistant working over MCP alone starts from ``arcavex_template_new`` (which scaffolds a
square and a story) and edits with ``arcavex_template_patch``. Until this grammar existed that
tool could address only ``nodes.<id>``, so nothing over the protocol could declare a print size,
a new variable, preview data, or a per-format patch — one assistant shipped a 9:16 "window
poster" because A3 was unreachable. These tests pin the top-level ``template patch`` grammar
and the guarantees around it: the patched template must still compile for every declared
format, and a patch *embedded* in a format or locale stays node-scoped.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import Facade, PatchOp
from arcavex.kernel.ir.models import CompiledText
from arcavex.services.fsutil import sha256_bytes
from arcavex.services.template.compiler import Compiler
from arcavex.services.template.loader import load_yaml

# A6 at 300 dpi with a print bleed: small enough to render in a unit test, print-shaped enough
# to prove a mm/dpi/bleed canvas round-trips through the patch grammar.
_A6 = {"canvas": {"width": "105mm", "height": "148mm", "dpi": 300, "bleed": "3mm"}}


@pytest.fixture()
def card(tmp_path: Path) -> tuple[Facade, Path]:
    facade = build_facade()
    target = tmp_path / "card"
    assert facade.scaffold_template("card", target).ok
    return facade, target


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])


def _title_size_pt(target: Path, fmt: str) -> float:
    doc = Compiler().compile(target, None, fmt, None, None).document
    assert doc is not None
    title = next(c for c in doc.root.children if c.id == "title")
    assert isinstance(title, CompiledText)
    assert title.style.font_size_pt is not None
    return title.style.font_size_pt


# ------------------------------------------------------------------------------ formats
def test_set_declares_a_print_format_and_it_renders(
    card: tuple[Facade, Path], tmp_path: Path
) -> None:
    facade, target = card
    result = facade.patch_template(target, [PatchOp(set="formats.a6", value=_A6)])
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert result.applied == 1

    raw = load_yaml(target / "template.yaml")
    assert raw["formats"]["a6"]["canvas"] == _A6["canvas"]
    inspected = facade.inspect_template(target)
    assert {f.name for f in inspected.formats} == {"square", "story", "a6"}

    out = tmp_path / "a6.png"
    rendered = facade.render_file(target, None, "a6", output=out)
    assert rendered.ok, [d.model_dump() for d in rendered.diagnostics]
    width_px, height_px = _png_size(out)
    # 105 mm and 148 mm at 300 dpi.
    assert abs(width_px - 1240) <= 1 and abs(height_px - 1748) <= 1


def test_set_reaches_a_single_canvas_field(card: tuple[Facade, Path]) -> None:
    facade, target = card
    result = facade.patch_template(
        target, [PatchOp(set="formats.story.canvas.height", value="1350px")]
    )
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    story = next(f for f in facade.inspect_template(target).formats if f.name == "story")
    assert story.height == "1350px"


def test_remove_drops_a_format(card: tuple[Facade, Path]) -> None:
    facade, target = card
    result = facade.patch_template(target, [PatchOp(remove="formats.story")])
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert {f.name for f in facade.inspect_template(target).formats} == {"square"}


def test_set_adds_a_per_format_patch_and_list_indexes_reach_into_it(
    card: tuple[Facade, Path],
) -> None:
    facade, target = card
    assert facade.patch_template(target, [PatchOp(set="formats.a6", value=_A6)]).ok
    result = facade.patch_template(
        target,
        [
            PatchOp(
                set="formats.a6.patch",
                value=[{"set": "nodes.title.style.font_size", "value": "48pt"}],
            )
        ],
    )
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert _title_size_pt(target, "a6") == 48.0
    assert _title_size_pt(target, "square") != 48.0  # the patch is scoped to a6

    # A list index addresses one op inside the embedded patch, as it does inside 'effects'.
    tuned = facade.patch_template(
        target, [PatchOp(set="formats.a6.patch.0.value", value="40pt")]
    )
    assert tuned.ok, [d.model_dump() for d in tuned.diagnostics]
    assert _title_size_pt(target, "a6") == 40.0


def test_a_per_format_patch_addressing_a_missing_node_is_refused(
    card: tuple[Facade, Path],
) -> None:
    facade, target = card
    before = (target / "template.yaml").read_bytes()
    result = facade.patch_template(
        target,
        [PatchOp(set="formats.square.patch", value=[{"remove": "nodes.ghost"}])],
    )
    assert not result.ok
    assert any(d.code == "ARC-TPL-092" and "ghost" in d.message for d in result.diagnostics)
    assert (target / "template.yaml").read_bytes() == before


# ---------------------------------------------------------------- variables & preview data
def test_set_declares_a_variable_and_the_template_can_use_it(
    card: tuple[Facade, Path], tmp_path: Path
) -> None:
    facade, target = card
    ops = [
        PatchOp(
            set="variables.kicker",
            value={"type": "string", "required": False, "doc": "Small line above the title"},
        ),
        PatchOp(set="preview_data.kicker", value="NEW SEASON"),
        PatchOp(set="nodes.subtitle.text", value="{{ kicker | default('') }}"),
    ]
    result = facade.patch_template(target, ops)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert result.applied == 3

    inspected = facade.inspect_template(target)
    kicker = next(v for v in inspected.variables if v.name == "kicker")
    assert kicker.type == "string" and kicker.doc == "Small line above the title"
    assert inspected.preview_data["kicker"] == "NEW SEASON"
    rendered = facade.render_file(target, None, "square", output=tmp_path / "kicker.png")
    assert rendered.ok, [d.model_dump() for d in rendered.diagnostics]


def test_removing_preview_data_a_required_variable_needs_is_refused(
    card: tuple[Facade, Path],
) -> None:
    """The patched template must still compile for every declared format, or nothing lands."""
    facade, target = card
    before = (target / "template.yaml").read_bytes()
    result = facade.patch_template(target, [PatchOp(remove="preview_data.title")])
    assert not result.ok
    assert any(d.code == "ARC-TPL-014" for d in result.diagnostics)
    assert (target / "template.yaml").read_bytes() == before
    assert result.sha256 == sha256_bytes(before)


def test_a_canvas_that_does_not_parse_is_a_located_refusal(card: tuple[Facade, Path]) -> None:
    facade, target = card
    before = (target / "template.yaml").read_bytes()
    result = facade.patch_template(
        target,
        [PatchOp(set="formats.bad", value={"canvas": {"width": "wide", "height": "10mm"}})],
    )
    assert not result.ok
    located = [
        d
        for d in result.diagnostics
        if d.source is not None
        and d.source.keypath is not None
        and d.source.keypath.startswith("formats.bad.canvas.width")
    ]
    assert located, [d.model_dump() for d in result.diagnostics]
    assert (target / "template.yaml").read_bytes() == before


def test_errors_the_template_already_had_do_not_block_an_unrelated_edit(tmp_path: Path) -> None:
    """Only errors a patch *introduces* refuse it, so a broken template can still be repaired."""
    facade = build_facade()
    target = tmp_path / "broken"
    target.mkdir()
    (target / "template.yaml").write_text(
        """\
version: 0.1.0
variables:
  title: {type: string, required: true}
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 96}}
preview_data:
  title: "x"
root:
  type: group
  id: root
  children:
    - id: bg
      type: shape
      shape: rect
      style: {fill: "not-a-color"}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
""",
        encoding="utf-8",
    )
    result = facade.patch_template(target, [PatchOp(set="formats.a6", value=_A6)])
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert "a6" in load_yaml(target / "template.yaml")["formats"]


# ------------------------------------------------------------------------ locales & style
def test_set_creates_a_missing_section_ahead_of_root(card: tuple[Facade, Path]) -> None:
    facade, target = card
    result = facade.patch_template(
        target, [PatchOp(set="locales.fa", value={"direction": "rtl", "digits": "fa"})]
    )
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    text = (target / "template.yaml").read_text(encoding="utf-8")
    assert 0 < text.index("locales:") < text.index("root:")
    locales = facade.inspect_template(target).locales
    assert [(loc.name, loc.direction, loc.digits) for loc in locales] == [("fa", "rtl", "fa")]


def test_style_is_a_whole_value_and_an_unknown_pack_is_refused(
    card: tuple[Facade, Path],
) -> None:
    facade, target = card
    before = (target / "template.yaml").read_bytes()
    result = facade.patch_template(target, [PatchOp(set="style", value="no-such-pack")])
    assert not result.ok
    assert any(d.code.startswith("ARC-STY-") for d in result.diagnostics)
    assert (target / "template.yaml").read_bytes() == before


# ----------------------------------------------------------------------------- grammar
def test_insert_verbs_stay_node_only(card: tuple[Facade, Path]) -> None:
    facade, target = card
    before = (target / "template.yaml").read_bytes()
    result = facade.patch_template(
        target, [PatchOp(insert_after="formats.square", node=_A6)]
    )
    assert not result.ok
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-092")
    assert "nodes.<id>" in diag.message and "set" in diag.message
    assert (target / "template.yaml").read_bytes() == before


def test_an_unknown_root_lists_every_root(card: tuple[Facade, Path]) -> None:
    facade, target = card
    result = facade.patch_template(target, [PatchOp(set="canvas.width", value="10mm")])
    assert not result.ok
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-092")
    for root in ("nodes.<id>", "formats.<name>", "variables.<name>", "preview_data.<key>",
                 "locales.<name>", "'style'"):
        assert root in diag.message, diag.message


def test_a_section_root_needs_an_entry_name(card: tuple[Facade, Path]) -> None:
    facade, target = card
    result = facade.patch_template(target, [PatchOp(set="formats", value={})])
    assert not result.ok
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-092")
    assert "formats.<name>" in diag.message


# ------------------------------------------------------------------------ split templates
def test_a_split_template_is_patched_in_its_sidecar(
    card: tuple[Facade, Path], tmp_path: Path
) -> None:
    facade, target = card
    assert facade.split_template(target).ok
    result = facade.patch_template(target, [PatchOp(set="formats.a6", value=_A6)])
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert "a6" in load_yaml(target / "formats.yaml")
    assert "formats" not in load_yaml(target / "template.yaml")
    rendered = facade.render_file(target, None, "a6", output=tmp_path / "split-a6.png")
    assert rendered.ok, [d.model_dump() for d in rendered.diagnostics]


# -------------------------------------------------------------------- embedded patches
def test_an_embedded_format_patch_cannot_rewrite_formats(tmp_path: Path) -> None:
    """Template-level roots belong to 'template patch'; a format's own patch stays on nodes."""
    template = tmp_path / "t.yaml"
    template.write_text(
        """\
version: 0.1.0
formats:
  square:
    canvas: {width: 200px, height: 200px, dpi: 72}
    patch:
      - set: formats.square.canvas.width
        value: 10px
root:
  type: group
  id: root
  children: []
""",
        encoding="utf-8",
    )
    result = Compiler().compile(template, None, "square", None, None)
    diag = next(d for d in result.diagnostics if d.code == "ARC-TPL-092")
    assert "nodes.<id>" in diag.message and "template patch" in diag.message
    assert diag.source is not None and diag.source.keypath == "formats.square.patch[0]"

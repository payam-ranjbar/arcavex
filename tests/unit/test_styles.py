"""Style-pack tests: resolution, palette expressions, role defaults, presets, provenance."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.services.style import StyleResolver


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201
    return build_facade()


def _write(tmp_path: Path, text: str, name: str = "t.yaml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------------- resolver
def test_list_and_inspect_pop_art() -> None:
    resolver = StyleResolver()
    names = [p.name for p in resolver.list_packs()]
    assert "pop-art" in names
    pack = resolver.inspect("pop-art")
    assert pack.version == "0.1.0"
    assert "warhol_1" in pack.palettes
    assert "halftone" in pack.effect_presets
    assert "heading" in pack.roles


def test_resolve_by_version_and_by_local_file(tmp_path) -> None:  # noqa: ANN001
    resolver = StyleResolver()
    assert resolver.resolve("pop-art@0.1", tmp_path).version == "0.1.0"
    _write(
        tmp_path,
        "version: 9.9\npalettes: {duo: ['#000000', '#ffffff']}\n",
        name="mine.yaml",
    )
    pack = resolver.resolve("./mine.yaml", tmp_path)
    assert pack.version == "9.9" and pack.palettes["duo"][1] == "#ffffff"


def test_unknown_style_is_located() -> None:
    resolver = StyleResolver()
    from arcavex.kernel.diagnostics import DiagnosticError

    with pytest.raises(DiagnosticError) as exc:
        resolver.inspect("does-not-exist")
    assert exc.value.diagnostics[0].code == "ARC-STY-001"


# ------------------------------------------------------------------- compile integration
def test_palette_available_in_expressions(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "style: pop-art@0.1\n"
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      style: {fill: '{{ palette.warhol_1[0] }}'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    assert compiled.document is not None, [d.code for d in compiled.diagnostics]
    fill = compiled.document.root.children[0].style.fill
    assert fill is not None and abs(fill[0] - 1.0) < 0.01 and abs(fill[2] - 0.647) < 0.02


def test_style_role_applies_defaults(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "style: pop-art@0.1\n"
        "formats: {sq: {canvas: {width: 300px, height: 120px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: h\n      type: text\n      text: HELLO\n      style_role: heading\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    assert compiled.document is not None, [d.code for d in compiled.diagnostics]
    style = compiled.document.root.children[0].style
    assert style.font_weight == 900  # from the heading role default
    assert style.font_families and style.font_families[0] == "Inter"


def test_node_style_overrides_role(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "style: pop-art@0.1\n"
        "formats: {sq: {canvas: {width: 300px, height: 120px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: h\n      type: text\n      text: HELLO\n      style_role: heading\n"
        "      style: {font_weight: 400}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    assert compiled.document is not None, [d.code for d in compiled.diagnostics]
    assert compiled.document.root.children[0].style.font_weight == 400  # node wins over role


def test_effect_preset_expands(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "style: pop-art@0.1\n"
        "formats: {sq: {canvas: {width: 128px, height: 128px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#808080'}\n"
        "      effect_preset: halftone\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    assert compiled.document is not None, [d.code for d in compiled.diagnostics]
    effects = compiled.document.root.children[0].effects
    assert len(effects) == 1 and effects[0].name == "halftone"
    assert effects[0].params["pitch"] == pytest.approx(6.0)  # preset's pitch


def test_unknown_preset_and_role_located(facade, tmp_path) -> None:  # noqa: ANN001
    preset_tpl = _write(
        tmp_path,
        "style: pop-art@0.1\n"
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      effect_preset: sparkles\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
        name="preset.yaml",
    )
    diags = facade.validate_template(preset_tpl, format_name="sq")
    assert any(d.code == "ARC-STY-010" for d in diags)

    role_tpl = _write(
        tmp_path,
        "style: pop-art@0.1\n"
        "formats: {sq: {canvas: {width: 200px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: t\n      type: text\n      text: hi\n      style_role: banner\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
        name="role.yaml",
    )
    diags = facade.validate_template(role_tpl, format_name="sq")
    assert any(d.code == "ARC-STY-011" for d in diags)


def test_resolved_reports_style_layer(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "style: pop-art@0.1\n"
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#123456'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    report = facade.inspect_resolved(template, None, "sq", None)
    assert report.ok
    assert report.style == "pop-art@0.1.0"


def test_style_cli_overrides_template(facade, tmp_path) -> None:  # noqa: ANN001
    """--style overrides the template's own opt-in (resolution order, §4.1.4)."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      style: {fill: '{{ palette.warhol_2[0] }}'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, "pop-art@0.1")
    assert compiled.document is not None, [d.code for d in compiled.diagnostics]
    fill = compiled.document.root.children[0].style.fill
    assert fill is not None and fill[1] > 0.7  # warhol_2[0] = #00E5A0 (green)


def test_unknown_template_style_is_located(facade, tmp_path) -> None:  # noqa: ANN001
    """CR-3/DX-7: a template 'style:' naming a missing pack points at the style line."""
    template = _write(
        tmp_path,
        "style: does-not-exist@9\n"
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    diags = facade.validate_template(template, format_name="sq")
    sty = next(d for d in diags if d.code == "ARC-STY-001")
    assert sty.source is not None
    assert sty.source.file and sty.source.keypath == "style" and sty.source.line == 1


def test_style_cli_local_file_resolves_from_cwd(facade, tmp_path, monkeypatch) -> None:  # noqa: ANN001,E501
    """A CLI --style ./file.yaml resolves relative to the working directory, not the template."""
    tpl_dir = tmp_path / "tpl"
    tpl_dir.mkdir()
    template = tpl_dir / "t.yaml"
    template.write_text(
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      style: {fill: '{{ palette.duo[1] }}'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
        encoding="utf-8",
    )
    (tmp_path / "mine.yaml").write_text(
        "version: 1\npalettes: {duo: ['#000000', '#ffffff']}\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)  # ./mine.yaml lives in cwd, not beside the template
    compiled = facade._compiler.compile(template, None, "sq", None, "./mine.yaml")
    assert compiled.document is not None, [d.code for d in compiled.diagnostics]
    fill = compiled.document.root.children[0].style.fill
    assert fill is not None and fill[0] > 0.99  # duo[1] == #ffffff


def test_style_reports_carry_response_version(facade) -> None:  # noqa: ANN001
    """DX-3: style list/inspect carry the versioned-response envelope like every other command."""
    assert facade.list_styles().response_version == 1
    assert facade.inspect_style("pop-art").response_version == 1

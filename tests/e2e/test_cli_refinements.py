"""Regression cases drawn from the September agent-run analysis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcavex.bootstrap import build_facade
from arcavex.clients.cli import app
from arcavex.kernel.api import PatchOp
from arcavex.services.template.loader import load_yaml

runner = CliRunner()
TEMPLATE = """version: 0.1.0
formats: {square: {canvas: {width: 200px, height: 200px, dpi: 144}}}
locales: {en: {direction: ltr}}
preview_data: {}
root:
  id: root
  type: group
  children:
    - id: title
      type: text
      text: Hello
      style: {font: Inter, font_size: 20pt, color: "#111111"}
      constraints:
        anchor: {top: parent.top, start: parent.start}
        size: {w: fill, h: fit_content}
"""


@pytest.fixture()
def template(tmp_path: Path, arcavex_home: Path) -> Path:
    path = tmp_path / "template.yaml"
    path.write_text(TEMPLATE, encoding="utf-8")
    return path


def test_new_template_checks_and_renders_its_locale(tmp_path: Path, arcavex_home: Path) -> None:
    directory = tmp_path / "card"
    assert runner.invoke(app, ["template", "new", str(directory), "--json"]).exit_code == 0
    checked = runner.invoke(
        app, ["template", "check", str(directory), "-f", "square", "-l", "en", "--json"]
    )
    assert checked.exit_code == 0, checked.output
    rendered = runner.invoke(
        app,
        [
            "render",
            str(directory),
            "-f",
            "square",
            "-l",
            "en",
            "-o",
            str(tmp_path / "card.png"),
            "--json",
        ],
    )
    assert rendered.exit_code == 0, rendered.output


def test_preflight_collects_missing_structure_and_locale(
    tmp_path: Path, arcavex_home: Path
) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("version: 0.1.0\nunknown: true\nother: true\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path), "-l", "en", "--json"])
    errors = json.loads(result.stdout)["diagnostics"]
    assert {d["code"] for d in errors} == {
        "ARC-TPL-065",
        "ARC-TPL-004",
        "ARC-TPL-020",
        "ARC-TPL-100",
    }
    assert sum(d["code"] == "ARC-TPL-065" for d in errors) == 2


def test_numeric_expression_names_alternatives(template: Path) -> None:
    template.write_text(TEMPLATE.replace("font_size: 20pt", 'font_size: "{{ title_size }}px"'))
    result = runner.invoke(app, ["validate", str(template), "--json"])
    errors = json.loads(result.stdout)["diagnostics"]
    assert errors[0]["code"] == "ARC-TPL-069"
    assert errors[0]["source"]["keypath"].endswith("style.font_size")
    assert "format/locale" in errors[0]["hint"]
    assert "shrink_to_fit" in errors[0]["hint"]


@pytest.mark.parametrize("component", ["mask", "shape"])
def test_component_pixels_match_equivalent_points(
    template: Path, tmp_path: Path, component: str
) -> None:
    extra = (
        "      mask: {component: rounded_rect, params: {radius: 20px}}\n"
        if component == "mask"
        else "      generator: speech_bubble\n      params: {corner: 20px}\n"
    )
    source = TEMPLATE
    if component == "shape":
        source = source.replace("type: text", "type: shape").replace("      text: Hello\n", "")
        source = source.replace("h: fit_content", "h: 80pt")
    source = source.replace("      constraints:", extra + "      constraints:")
    facade = build_facade()
    template.write_text(source)
    pixels = facade.render_file(template, output=tmp_path / "pixels.png")
    template.write_text(source.replace("20px", "10pt"))
    points = facade.render_file(template, output=tmp_path / "points.png")
    assert pixels.ok and points.ok, (pixels.diagnostics, points.diagnostics)
    assert pixels.content_sha256 == points.content_sha256


def test_template_and_node_patches_apply_together(template: Path) -> None:
    result = build_facade().patch_template(
        template,
        [
            PatchOp(set="template.locales.fa", value={"direction": "rtl"}),
            PatchOp(set="nodes.title.text", value="Updated"),
        ],
    )
    assert result.ok, result.diagnostics
    raw = load_yaml(template)
    assert raw["locales"]["fa"]["direction"] == "rtl"
    assert raw["root"]["children"][0]["text"] == "Updated"


def test_bad_template_patch_keeps_entire_batch_unwritten(template: Path) -> None:
    before = template.read_bytes()
    result = build_facade().patch_template(
        template,
        [
            PatchOp(set="nodes.title.text", value="Updated"),
            PatchOp(set="template.locale.en", value={}),
        ],
    )
    assert not result.ok
    assert template.read_bytes() == before


def test_split_section_patch_never_shadows_sidecar(template: Path) -> None:
    template.write_text(TEMPLATE.replace("locales: {en: {direction: ltr}}\n", ""))
    sidecar = template.parent / "locales.yaml"
    sidecar.write_text("en: {direction: ltr}\n")
    before = template.read_bytes(), sidecar.read_bytes()
    result = build_facade().patch_template(template, [PatchOp(set="template.locales", value={})])
    assert not result.ok
    assert (template.read_bytes(), sidecar.read_bytes()) == before


def test_project_layout_honors_override_patch(
    template: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = template.parent
    (project / "project.yaml").write_text(
        "name: card\ntemplate: ./template.yaml\nformats: [square]\nlocales: [en]\n"
    )
    overrides = project / "overrides"
    overrides.mkdir()
    (overrides / "template.patch.yaml").write_text(
        "- set: nodes.title.constraints.anchor.top\n  value: parent.top+30pt\n"
    )
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["layout", "inspect", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["format"] == "square" and payload["locale"] == "en"
    assert payload["root"]["children"][0]["bounds_pt"][1] == 30
    assert not (project / "outputs").exists()


def test_project_layout_requires_single_target(template: Path) -> None:
    (template.parent / "project.yaml").write_text(
        "name: card\ntemplate: ./template.yaml\nformats: [square, story]\nlocales: [en]\n"
    )
    result = runner.invoke(app, ["layout", "inspect", "--project", str(template.parent), "--json"])
    assert result.exit_code == 1, result.output
    assert "single project target" in json.loads(result.stdout)["diagnostics"][0]["message"]


def test_piped_human_output_preserves_long_filename(tmp_path: Path, arcavex_home: Path) -> None:
    missing = tmp_path / ("long-name-" * 17 + ".yaml")
    result = runner.invoke(app, ["render", str(missing)])
    assert str(missing) in result.output
    doctor = runner.invoke(app, ["doctor"])
    assert "commit " in doctor.output
    assert "│" not in doctor.output
    targets = runner.invoke(app, ["skill", "install", "--list", "--path", str(missing)])
    assert str(missing / "arcavex-design-studio") in targets.output


def test_documented_minimal_image_card_renders(tmp_path: Path, arcavex_home: Path) -> None:
    import re
    import shutil

    root = Path(__file__).resolve().parents[2]
    manual = (root / "skills/arcavex-design-studio/SKILL.md").read_text(encoding="utf-8")
    example = re.search(r"```yaml\n(.*?)\n```", manual, re.DOTALL)
    assert example is not None
    (tmp_path / "template.yaml").write_text(example.group(1) + "\n")
    shutil.copyfile(root / "tests/fixtures/basic-poster/logo.png", tmp_path / "photo.png")
    rendered = build_facade().render_file(
        tmp_path, format_name="square", locale="en", output=tmp_path / "card.png"
    )
    assert rendered.ok, rendered.diagnostics


# ------------------------------------------------------------------- A5 scoped patch
def test_cli_template_patch_format_upserts_exactly_one_op(template: Path) -> None:
    """--format writes into formats.<F>.patch and a re-set updates it instead of duplicating."""
    first = runner.invoke(
        app,
        [
            "template", "patch", str(template), "--format", "square",
            "--set", "nodes.title.style.color", "--value", '"#ff0000"',
        ],
    )
    assert first.exit_code == 0, first.output
    assert len(load_yaml(template)["formats"]["square"]["patch"]) == 1

    second = runner.invoke(
        app,
        [
            "template", "patch", str(template), "--format", "square",
            "--set", "nodes.title.style.color", "--value", '"#00ff00"',
        ],
    )
    assert second.exit_code == 0, second.output
    patch = load_yaml(template)["formats"]["square"]["patch"]
    assert len(patch) == 1
    assert patch[0]["value"] == "#00ff00"


def test_cli_template_patch_unknown_format_is_located(template: Path) -> None:
    """An unknown --format is a located ARC-TPL-092 and leaves the file byte-for-byte intact."""
    before = template.read_bytes()
    result = runner.invoke(
        app,
        [
            "template", "patch", str(template), "--format", "nope",
            "--set", "nodes.title.style.color", "--value", '"#fff"', "--json",
        ],
    )
    assert result.exit_code == 1, result.output
    diagnostics = json.loads(result.stdout)["diagnostics"]
    assert diagnostics[0]["code"] == "ARC-TPL-092"
    assert diagnostics[0]["source"]["keypath"] == "formats.nope"
    assert template.read_bytes() == before


def test_cli_template_patch_locale_targets_locale_patch_and_fonts(template: Path) -> None:
    """--locale writes a node op into locales.<L>.patch and fonts.<Family> into fonts."""
    node = runner.invoke(
        app,
        [
            "template", "patch", str(template), "--locale", "en",
            "--set", "nodes.title.text", "--value", '"Hi"',
        ],
    )
    assert node.exit_code == 0, node.output
    font = runner.invoke(
        app,
        [
            "template", "patch", str(template), "--locale", "en",
            "--set", "fonts.Inter", "--value", "Vazirmatn",
        ],
    )
    assert font.exit_code == 0, font.output
    raw = load_yaml(template)
    assert len(raw["locales"]["en"]["patch"]) == 1
    assert raw["locales"]["en"]["fonts"]["Inter"] == "Vazirmatn"


def test_cli_template_patch_format_and_locale_target_narrowest_block(template: Path) -> None:
    """Both flags address locales.<L>.formats.<F>.patch, not the broader lists."""
    result = runner.invoke(
        app,
        [
            "template", "patch", str(template), "--locale", "en", "--format", "square",
            "--set", "nodes.title.style.font_size", "--value", '"40pt"',
        ],
    )
    assert result.exit_code == 0, result.output
    raw = load_yaml(template)
    assert len(raw["locales"]["en"]["formats"]["square"]["patch"]) == 1
    assert "patch" not in raw["formats"]["square"]
    assert "patch" not in raw["locales"]["en"]


def test_cli_template_patch_unset_removes_op(template: Path) -> None:
    """--unset deletes the op addressing the same --set path instead of writing one."""
    runner.invoke(
        app,
        [
            "template", "patch", str(template), "--format", "square",
            "--set", "nodes.title.style.color", "--value", '"#ff0000"',
        ],
    )
    result = runner.invoke(
        app,
        [
            "template", "patch", str(template), "--format", "square",
            "--unset", "--set", "nodes.title.style.color",
        ],
    )
    assert result.exit_code == 0, result.output
    assert load_yaml(template)["formats"]["square"]["patch"] == []


def test_cli_template_patch_split_writes_owner_sidecar(template: Path) -> None:
    """A split template is patched in formats.yaml/locales.yaml, never back into template.yaml."""
    split = runner.invoke(app, ["template", "split", str(template)])
    assert split.exit_code == 0, split.output
    formats = template.parent / "formats.yaml"
    locales = template.parent / "locales.yaml"
    assert formats.is_file() and locales.is_file()

    before = template.read_bytes()
    result = runner.invoke(
        app,
        [
            "template", "patch", str(template.parent), "--format", "square",
            "--set", "nodes.title.style.color", "--value", '"#ff0000"',
        ],
    )
    assert result.exit_code == 0, result.output
    assert "formats.yaml" in result.output
    assert template.read_bytes() == before
    assert "nodes.title.style.color" in formats.read_text(encoding="utf-8")

    before = template.read_bytes()
    result = runner.invoke(
        app,
        [
            "template", "patch", str(template.parent), "--locale", "en",
            "--set", "nodes.title.text", "--value", '"Hi"',
        ],
    )
    assert result.exit_code == 0, result.output
    assert "locales.yaml" in result.output
    assert template.read_bytes() == before
    assert "nodes.title.text" in locales.read_text(encoding="utf-8")

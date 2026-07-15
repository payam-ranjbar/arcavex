"""Golden-image tests: every effect on a fixture, a fused chain, halftone, IPEN, pop-art.

Each effect is rendered onto a fixed tonal subject and compared perceptually (SSIM/DSSIM) to a
per-platform golden (spec §8.5). Regenerate with ``ARCAVEX_UPDATE_GOLDENS=1``. These are the
regression net for the effect pipeline: a broken effect, a fusion error, or a shifted composite
moves the DSSIM well past the 0.003 budget.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from harness import compare_to_golden, load_png

from arcavex.bootstrap import build_facade

_REPO = Path(__file__).resolve().parents[2]
_SUBJECT = _REPO / "tests" / "golden" / "fixtures" / "subject.png"


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201 - pytest fixture
    return build_facade()


def _probe_template(effects_yaml: str, subject: str) -> str:
    """A 256² probe scene: a light background plus one effect-bearing subject node."""
    if subject == "image":
        node = (
            f"    - id: subject\n"
            f"      type: image\n"
            f"      asset: {_SUBJECT.as_posix()!r}\n"
            f"      fit: cover\n"
            f"      effects:\n{effects_yaml}\n"
            f"      constraints: {{anchor: {{center_x: parent.center_x, "
            f"center_y: parent.center_y}}, size: {{w: 68%, h: 68%}}}}\n"
        )
    else:
        node = (
            f"    - id: subject\n"
            f"      type: shape\n"
            f"      shape: rrect\n"
            f"      style: {{fill: '#e0356b', corner_radius: 16px}}\n"
            f"      effects:\n{effects_yaml}\n"
            f"      constraints: {{anchor: {{center_x: parent.center_x, "
            f"center_y: parent.center_y}}, size: {{w: 55%, h: 55%}}}}\n"
        )
    return (
        "formats: {square: {canvas: {width: 256px, height: 256px, dpi: 96}}}\n"
        "seed: 5\n"
        "root:\n"
        "  id: root\n"
        "  type: group\n"
        "  children:\n"
        "    - id: bg\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#ececec'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: 100%, h: 100%}}\n"
        f"{node}"
    )


def _render(facade, tmp_path: Path, template_text: str, name: str):  # noqa: ANN001,ANN202
    template = tmp_path / f"{name}.yaml"
    template.write_text(template_text, encoding="utf-8")
    out = tmp_path / f"{name}.png"
    result = facade.render_file(template, format_name="square", output=out)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    return load_png(out)


# name -> (effects YAML block, subject kind)
_EFFECT_PROBES: dict[str, tuple[str, str]] = {
    "blur": ("        - {name: blur, params: {radius: 3pt}}", "image"),
    "grain": ("        - {name: grain, params: {amount: 0.12}}", "image"),
    "noise": ("        - {name: noise, params: {amount: 0.15}}", "image"),
    "ink-bleed": ("        - {name: ink-bleed, params: {radius: 2pt}}", "shape"),
    "halftone": (
        "        - {name: halftone, params: {pitch: 6pt, angle: 15, ink: '#111111'}}", "image"
    ),
    "channel-offset": (
        "        - {name: channel-offset, params: {distance: 3pt, angle: 20}}", "image"
    ),
    "edge-wear": ("        - {name: edge-wear, params: {amount: 0.5}}", "shape"),
    "palette-map": (
        "        - {name: palette-map, params: {colors: ['#101033','#ff3ea5','#ffd600']}}",
        "image",
    ),
    "duotone": (
        "        - {name: duotone, params: {shadow: '#101033', highlight: '#ffd600'}}", "image"
    ),
    "threshold": ("        - {name: threshold, params: {level: 0.5}}", "image"),
    "grade": (
        "        - {name: grade, params: {contrast: 1.4, saturation: 0.5, brightness: 0.05}}",
        "image",
    ),
    "posterize": ("        - {name: posterize, params: {levels: 3}}", "image"),
    "drop-shadow": (
        "        - {name: drop-shadow, params: {dx: 8pt, dy: 10pt, blur: 5pt}}", "shape"
    ),
    "glow": (
        "        - {name: glow, params: {radius: 10pt, color: '#00e5ff'}}", "shape"
    ),
    "torn-paper": (
        "        - {name: torn-paper, params: {amplitude: 6pt, segment: 12pt}}", "shape"
    ),
}


@pytest.mark.parametrize("effect_name", sorted(_EFFECT_PROBES))
def test_effect_golden(facade, tmp_path, effect_name):  # noqa: ANN001,ANN201
    effects_yaml, subject = _EFFECT_PROBES[effect_name]
    text = _probe_template(effects_yaml, subject)
    array = _render(facade, tmp_path, text, f"effect-{effect_name}")
    compare_to_golden(f"effect-{effect_name}", array)


def test_fused_color_chain_golden(facade, tmp_path):  # noqa: ANN001,ANN201
    """A three-effect color chain (two fusing matrices + a table) rendered on the fixture."""
    effects = (
        "        - {name: grade, params: {saturation: 0.6, contrast: 1.2}}\n"
        "        - {name: duotone, params: {shadow: '#0a0a2a', highlight: '#ffd600'}}\n"
        "        - {name: posterize, params: {levels: 4}}"
    )
    text = _probe_template(effects, "image")
    array = _render(facade, tmp_path, text, "fused-color-chain")
    compare_to_golden("fused-color-chain", array)


def test_halftone_sksl_golden(facade, tmp_path):  # noqa: ANN001,ANN201
    """The SkSL halftone at two angles, to lock in the shader output."""
    effects = (
        "        - {name: duotone, params: {shadow: '#101033', highlight: '#00c2ff'}}\n"
        "        - {name: halftone, params: {pitch: 5pt, angle: 45, ink: '#101033'}}"
    )
    text = _probe_template(effects, "image")
    array = _render(facade, tmp_path, text, "halftone-sksl")
    compare_to_golden("halftone-sksl", array)


def test_pop_art_grid_golden(facade):  # noqa: ANN001,ANN201
    """Golden case #3: the full pop-art Warhol grid example."""
    template = _REPO / "examples" / "pop-art-grid" / "template.yaml"
    data = _REPO / "examples" / "pop-art-grid" / "data.yaml"
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "popart.png"
        result = facade.render_file(template, data=data, format_name="square", output=out)
        assert result.ok, [d.model_dump() for d in result.diagnostics]
        array = load_png(out)
    compare_to_golden("pop-art-grid", array)


@pytest.mark.parametrize("locale", ["en", "fa"])
def test_ipen_square_golden(facade, locale):  # noqa: ANN001,ANN201
    """Golden case #2 (square format): the IPEN bilingual poster in each locale."""
    template = _REPO / "examples" / "ipen-bilingual" / "template.yaml"
    data = _REPO / "examples" / "ipen-bilingual" / "data.yaml"
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / f"ipen-{locale}.png"
        result = facade.render_file(
            template, data=data, format_name="square", locale=locale, output=out
        )
        assert result.ok, [d.model_dump() for d in result.diagnostics]
        array = load_png(out)
    compare_to_golden(f"ipen-square-{locale}", array)

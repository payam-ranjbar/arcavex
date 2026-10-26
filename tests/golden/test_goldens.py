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
    "ink-bleed": ("        - {name: ink-bleed, params: {radius: 3pt}}", "image"),
    "halftone": (
        "        - {name: halftone, params: {pitch: 6pt, angle: 15, ink: '#111111'}}", "image"
    ),
    "channel-offset": (
        "        - {name: channel-offset, params: {distance: 3pt, angle: 20}}", "image"
    ),
    "edge-wear": ("        - {name: edge-wear, params: {amount: 0.85}}", "shape"),
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


def test_linear_fade_mask_golden(facade, tmp_path):  # noqa: ANN001,ANN201
    """A photo with a directional alpha fade over a diamond-lattice patterned background."""
    text = (
        "formats: {square: {canvas: {width: 256px, height: 256px, dpi: 96}}}\n"
        "seed: 5\n"
        "root:\n"
        "  id: root\n"
        "  type: group\n"
        "  children:\n"
        "    - id: bg\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#101820'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: 100%, h: 100%}}\n"
        "    - id: pattern\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#3aa0ff'}\n"
        "      mask: {component: diamond_grid, params: {cell: 22pt, gutter: 8pt, angle: 45}}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: 100%, h: 100%}}\n"
        "    - id: photo\n"
        "      type: image\n"
        f"      asset: {_SUBJECT.as_posix()!r}\n"
        "      fit: cover\n"
        "      mask: {component: linear_fade, params: {direction: to_bottom, "
        "start: 0.1, end: 0.85}}\n"
        "      constraints: {anchor: {center_x: parent.center_x, center_y: parent.center_y}, "
        "size: {w: 68%, h: 68%}}\n"
    )
    array = _render(facade, tmp_path, text, "mask-linear-fade")
    compare_to_golden("mask-linear-fade", array)


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


def test_basic_poster_golden(facade):  # noqa: ANN001,ANN201
    """Golden case #3: a full multi-node poster render (shapes, image, shrink-to-fit text)."""
    template = _REPO / "tests" / "fixtures" / "basic-poster" / "template.yaml"
    data = _REPO / "tests" / "fixtures" / "basic-poster" / "data.yaml"
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "basic.png"
        result = facade.render_file(template, data=data, format_name="square", output=out)
        assert result.ok, [d.model_dump() for d in result.diagnostics]
        array = load_png(out)
    compare_to_golden("basic-poster", array)


@pytest.mark.parametrize("locale", ["en", "fa"])
def test_bilingual_square_golden(facade, locale):  # noqa: ANN001,ANN201
    """Golden case #2 (square format): the bilingual fixture in each locale."""
    template = _REPO / "tests" / "fixtures" / "bilingual-poster" / "template.yaml"
    data = _REPO / "tests" / "fixtures" / "bilingual-poster" / "data.yaml"
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / f"bilingual-{locale}.png"
        result = facade.render_file(
            template, data=data, format_name="square", locale=locale, output=out
        )
        assert result.ok, [d.model_dump() for d in result.diagnostics]
        array = load_png(out)
    compare_to_golden(f"bilingual-square-{locale}", array)


def test_editor_transforms_golden(facade, tmp_path):  # noqa: ANN001,ANN201
    """Golden for the Phase 2 transform contract: translate, scale, rotate, and all three.

    Four identical squares, each under one transform, over a grid of hairline rules that make a
    one-pixel drift visible. This is the regression net for the composition order — if solver
    and backend ever disagree again, the squares detach from their painted positions.
    """
    template = tmp_path / "transforms.yaml"
    template.write_text(
        "formats: {square: {canvas: {width: 256px, height: 256px, dpi: 96}}}\n"
        "root:\n"
        "  id: root\n"
        "  type: group\n"
        "  children:\n"
        "    - id: bg\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#f4f2ec'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}\n"
        "    - id: rule-h\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#c9c4b8'}\n"
        "      constraints: {anchor: {top: parent.top+128px, left: parent.left}, "
        "size: {w: fill, h: 1px}}\n"
        "    - id: rule-v\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#c9c4b8'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left+128px}, "
        "size: {w: 1px, h: fill}}\n"
        "    - id: translated\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#e0356b'}\n"
        "      transform: {translate: [24, 12]}\n"
        "      constraints: {anchor: {top: parent.top+24px, left: parent.left+24px}, "
        "size: {w: 56px, h: 56px}}\n"
        "    - id: scaled\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#2b6cb0'}\n"
        "      transform: {scale: [1.5, 0.75]}\n"
        "      constraints: {anchor: {top: parent.top+24px, left: parent.left+152px}, "
        "size: {w: 56px, h: 56px}}\n"
        "    - id: rotated\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#2f855a'}\n"
        "      transform: {rotate: 30}\n"
        "      constraints: {anchor: {top: parent.top+152px, left: parent.left+24px}, "
        "size: {w: 56px, h: 56px}}\n"
        "    - id: combined\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#b7791f'}\n"
        "      transform: {translate: [-10, 6], rotate: 20, scale: 1.25, origin: top_left}\n"
        "      constraints: {anchor: {top: parent.top+152px, left: parent.left+152px}, "
        "size: {w: 56px, h: 56px}}\n",
        encoding="utf-8",
    )
    out = tmp_path / "transforms.png"
    result = facade.render_file(template, format_name="square", output=out)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    compare_to_golden("editor-transforms", load_png(out))


@pytest.mark.parametrize(
    ("case", "data", "format_name", "locale"),
    [
        ("name-1-line", "data-short.yaml", "square", "en"),
        ("name-2-lines", "data-long.yaml", "square", "en"),
        ("rtl", "data-short.yaml", "square", "fa"),
        ("gap-format-patch", "data-long.yaml", "story", "en"),
    ],
)
def test_stack_card_golden(facade, tmp_path, case, data, format_name, locale):  # noqa: ANN001,ANN201
    """A vertical stack of variable-height text: even gaps, RTL packing, a patched gap (A2)."""
    fixture = _REPO / "tests" / "fixtures" / "stack-card"
    out = tmp_path / f"stack-{case}.png"
    result = facade.render_file(
        fixture / "template.yaml", data=fixture / data, format_name=format_name, locale=locale,
        output=out,
    )
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    compare_to_golden(f"stack-card-{case}", load_png(out))


def test_hard_break_golden(facade, tmp_path):  # noqa: ANN001,ANN201
    """Explicit ``\\n`` breaks in LTR and RTL text, and a third line cut by ``max_lines: 2``.

    Each text box hugs its lines (``h: fit_content``) and an orange rule sits under it, so the
    picture shows the box height the line count produced: two lines for each block, including
    the three-line value whose cap now counts its hard breaks (before, it counted one line and
    the box grew to all three).
    """

    def block(node_id: str, top: str, text: str, extra: str) -> str:
        return (
            f"    - id: {node_id}\n"
            "      type: text\n"
            f"      text: {text}\n"
            f"      {extra}\n"
            "      fit: {policy: wrap, max_lines: 2}\n"
            f"      constraints: {{anchor: {{top: {top}, left: parent.left+16px}}, "
            "size: {w: 224px, h: fit_content}}\n"
            f"    - id: {node_id}-rule\n"
            "      type: shape\n"
            "      shape: rect\n"
            "      style: {fill: '#f07828'}\n"
            f"      constraints: {{anchor: {{top: {node_id}.bottom+4px, left: parent.left+16px}}, "
            "size: {w: 224px, h: 3px}}\n"
        )

    text = (
        "formats: {square: {canvas: {width: 256px, height: 256px, dpi: 96}}}\n"
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
        + block("ltr", "parent.top+16px", '"First line\\nSecond line"',
                "style: {font: Inter, font_size: 16pt, color: black}")
        + block("rtl", "ltr-rule.bottom+16px", '"\u0633\u0637\u0631 \u0627\u0648\u0644'
                '\\n\u0633\u0637\u0631 \u062f\u0648\u0645"',
                "style: {font: Vazirmatn, font_size: 16pt, color: black}\n"
                "      paragraph: {direction: rtl, align: start}")
        + block("capped", "rtl-rule.bottom+16px", '"One\\nTwo\\nThree"',
                "style: {font: Inter, font_size: 16pt, color: black}")
    )
    array = _render(facade, tmp_path, text, "text-hard-break")
    compare_to_golden("text-hard-break", array)


def test_balanced_wrap_golden(facade, tmp_path):  # noqa: ANN001,ANN201
    """Golden for `fit.balance`: the same copy wrapped greedily (top) and balanced (bottom).

    Both sit in the same 224px box, drawn as a pale column. Greedy wrapping fills the first line
    and leaves a short second one; the balanced block holds the same two lines at the tightest
    width, centered in the box.
    """

    def block(node_id: str, top: str, balance: str) -> str:
        return (
            f"    - id: {node_id}\n"
            "      type: text\n"
            "      text: 'The quick brown fox jumps over the dog'\n"
            "      style: {font: Inter, font_size: 18pt, color: '#1a1a1a'}\n"
            "      paragraph: {align: center}\n"
            f"      fit: {{policy: wrap, balance: {balance}}}\n"
            f"      constraints: {{anchor: {{top: {top}, left: parent.left+16px}}, "
            "size: {w: 224px, h: fit_content}}\n"
        )

    template = (
        "formats: {square: {canvas: {width: 256px, height: 288px, dpi: 96}}}\n"
        "root:\n"
        "  id: root\n"
        "  type: group\n"
        "  children:\n"
        "    - id: bg\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#f4f2ec'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}\n"
        "    - id: box\n"
        "      type: shape\n"
        "      shape: rect\n"
        "      style: {fill: '#e2ddd0'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left+16px}, "
        "size: {w: 224px, h: fill}}\n"
        + block("greedy", "parent.top+24px", "false")
        + block("balanced", "greedy.bottom+40px", "true")
    )
    array = _render(facade, tmp_path, template, "text-balanced-wrap")
    compare_to_golden("text-balanced-wrap", array)

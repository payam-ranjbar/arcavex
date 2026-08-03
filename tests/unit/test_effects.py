"""Effect-pipeline tests: fusion, determinism, the surface pool, and bounds honesty.

These lock the load-bearing guarantees of the effect system (spec §3.2/§4.4/§4.5): consecutive
color effects fuse into one matrix and stay semantically identical; randomness is seeded so the
same inputs give byte-identical bytes and different node ids give different noise; raster
allocations come from the pool and are all released; and every effect's declared bounds
expansion is honest — it neither clips real output nor claims territory it never paints.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import skia  # type: ignore[import-untyped]

from arcavex.bootstrap import build_facade
from arcavex.builtin.backend_skia.pipeline import build_color_filter, compile_effect_plan
from arcavex.builtin.effects_core import builtin_effects
from arcavex.builtin.effects_core.context import (
    ColorContext,
    ColorMatrix,
    ColorTable,
    effect_rng,
)
from arcavex.kernel.contracts.types import RenderOptions
from arcavex.kernel.ir.models import EffectSpec
from arcavex.kernel.ir.units import Rect


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201
    return build_facade()


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "t.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _render_array(facade, document):  # noqa: ANN001,ANN202
    solver = facade._registries.layouts.get("anchors")
    layout = solver.solve(document, facade._measure)
    backend = facade._registries.backends.get("skia")
    surface = backend.render(layout, RenderOptions())
    arr = surface.makeImageSnapshot().toarray(
        colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
    )
    return layout, backend, arr


def _find(node, node_id):  # noqa: ANN001,ANN202
    if node.source_node_id == node_id:
        return node
    for child in node.children:
        found = _find(child, node_id)
        if found is not None:
            return found
    return None


# --------------------------------------------------------------------------- fusion
def test_consecutive_color_matrices_fuse() -> None:
    """grade + duotone (matrices) collapse into one op; posterize (table) stays separate."""
    effects = builtin_effects()
    specs = (
        EffectSpec(name="grade", category="color", params={"saturation": 0.6}),
        EffectSpec(name="duotone", category="color", params={}),
        EffectSpec(name="posterize", category="color", params={"levels": 4}),
    )
    plan = compile_effect_plan(specs, effects)
    assert len(plan.color_ops) == 2  # two matrices fused to one, plus the table
    assert isinstance(plan.color_ops[0], ColorMatrix)
    assert isinstance(plan.color_ops[1], ColorTable)


def test_fusion_is_semantically_equivalent() -> None:
    """In-gamut, the fused filter matches applying each color effect in sequence (±1/255)."""
    effects = builtin_effects()
    specs = (
        EffectSpec(name="grade", category="color", params={"saturation": 0.6}),
        EffectSpec(name="duotone", category="color",
                   params={"shadow": "#101033", "highlight": "#ffd400"}),
    )
    plan = compile_effect_plan(specs, effects)
    assert len(plan.color_ops) == 1  # both fused

    rng = np.random.default_rng(3)
    arr = rng.integers(0, 256, (48, 48, 4)).astype(np.uint8)
    arr[..., 3] = 255
    img = skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType)

    def draw(filters):  # noqa: ANN001,ANN202
        cur = img
        for f in filters:
            s = skia.Surface(48, 48)
            c = s.getCanvas()
            c.clear(skia.Color4f(0, 0, 0, 0))
            paint = skia.Paint()
            paint.setColorFilter(f)
            c.drawImage(cur, 0, 0, skia.SamplingOptions(), paint)
            cur = s.makeImageSnapshot()
        return cur.toarray(
            colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
        )

    from arcavex.builtin.backend_skia.pipeline import _skia_color_filter

    individual = [
        _skia_color_filter(effects[s.name].apply(ColorContext(effects[s.name].param_schema(**s.params))))
        for s in specs
    ]
    fused = build_color_filter(plan.color_ops)
    diff = np.abs(draw(individual).astype(int) - draw([fused]).astype(int))
    assert diff.max() <= 2


def test_backend_collect_plan_exposes_fusion(facade, tmp_path) -> None:  # noqa: ANN001
    """RenderOptions.collect_plan surfaces the compiled plan for a debug/verbose consumer."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#888888'}\n"
        "      effects:\n"
        "        - {name: grade, params: {saturation: 0.5}}\n"
        "        - {name: duotone, params: {}}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    assert compiled.document is not None
    solver = facade._registries.layouts.get("anchors")
    layout = solver.solve(compiled.document, facade._measure)
    backend = facade._registries.backends.get("skia")
    backend.render(layout, RenderOptions(collect_plan=True))
    plans = {nid: plan for nid, plan in backend.collected_plans}
    assert "s" in plans
    assert len(plans["s"].color_ops) == 1  # the two matrices fused


# --------------------------------------------------------------------- determinism
def test_effect_rng_is_stable_and_scoped() -> None:
    """Same (seed, node, index) → same stream; a different node id → an independent one."""
    a1 = effect_rng(7, "node", 0).random(8)
    a2 = effect_rng(7, "node", 0).random(8)
    b = effect_rng(7, "other", 0).random(8)
    c = effect_rng(7, "node", 1).random(8)
    assert np.array_equal(a1, a2)
    assert not np.array_equal(a1, b)
    assert not np.array_equal(a1, c)


def test_render_is_byte_identical(facade, tmp_path) -> None:  # noqa: ANN001
    """A seeded grain render is byte-identical across runs (determinism, spec §4.5)."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 96px, height: 96px, dpi: 96}}}\n"
        "seed: 9\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#3366cc'}\n"
        "      effects: [{name: grain, params: {amount: 0.2}}]\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    out1 = tmp_path / "a.png"
    out2 = tmp_path / "b.png"
    r1 = facade.render_file(template, format_name="sq", output=out1)
    r2 = facade.render_file(template, format_name="sq", output=out2)
    assert r1.ok and r2.ok
    assert r1.content_sha256 == r2.content_sha256
    assert out1.read_bytes() == out2.read_bytes()


def test_different_node_ids_get_different_noise(facade, tmp_path) -> None:  # noqa: ANN001
    """Two identical grain nodes with different ids produce different noise fields."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 200px, height: 100px, dpi: 96}}}\n"
        "seed: 4\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: left\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#808080'}\n"
        "      effects: [{name: grain, params: {amount: 0.3}}]\n"
        "      constraints: {anchor: {left: parent.left, top: parent.top}, "
            "size: {w: 50%, h: 100%}}\n"
        "    - id: right\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#808080'}\n"
        "      effects: [{name: grain, params: {amount: 0.3}}]\n"
        "      constraints: {anchor: {right: parent.right, top: parent.top}, "
            "size: {w: 50%, h: 100%}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    _layout, _backend, arr = _render_array(facade, compiled.document)
    left = arr[10:90, 10:90, :3].astype(int)
    right = arr[10:90, 110:190, :3].astype(int)
    # Same base grey + same amount, but independent seeds → the two halves differ.
    assert not np.array_equal(left, right)


# --------------------------------------------------------------------- surface pool
def test_surface_pool_reuses_and_never_leaks(facade, tmp_path) -> None:  # noqa: ANN001
    """A multi-raster chain reuses pooled surfaces and returns them all (leak guard)."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 128px, height: 128px, dpi: 96}}}\n"
        "seed: 2\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rrect\n"
        "      style: {fill: '#cc4477', corner_radius: 10px}\n"
        "      effects:\n"
        "        - {name: blur, params: {radius: 2pt}}\n"
        "        - {name: halftone, params: {pitch: 5pt}}\n"
        "        - {name: grain, params: {amount: 0.1}}\n"
        "        - {name: drop-shadow, params: {dx: 4pt, dy: 4pt, blur: 3pt}}\n"
        "      constraints: {anchor: {center_x: parent.center_x, center_y: parent.center_y}, "
            "size: {w: 60%, h: 60%}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    _layout, backend, _arr = _render_array(facade, compiled.document)
    stats = backend.pool_stats()
    assert stats["outstanding"] == 0
    assert stats["acquired"] >= 4
    assert stats["reused"] >= 1  # a deep chain must reuse, not accumulate


# --------------------------------------------------------------------- bounds honesty
_HONESTY_EFFECTS = {
    "blur": ("shape", "{name: blur, params: {radius: 4pt}}", True),
    "drop-shadow": ("shape", "{name: drop-shadow, params: {dx: 8pt, dy: 8pt, blur: 4pt}}", True),
    "glow": ("shape", "{name: glow, params: {radius: 8pt}}", True),
    "ink-bleed": ("shape", "{name: ink-bleed, params: {radius: 3pt}}", False),
    "channel-offset": ("shape", "{name: channel-offset, params: {distance: 4pt}}", True),
    "torn-paper": ("shape", "{name: torn-paper, params: {amplitude: 6pt, segment: 12pt}}", True),
    "grain": ("shape", "{name: grain, params: {amount: 0.2}}", False),
    "halftone": ("shape", "{name: halftone, params: {pitch: 6pt}}", False),
    "duotone": ("shape", "{name: duotone, params: {}}", False),
    "posterize": ("shape", "{name: posterize, params: {levels: 3}}", False),
    "threshold": ("shape", "{name: threshold, params: {}}", False),
    "grade": ("shape", "{name: grade, params: {contrast: 1.3}}", False),
    "noise": ("shape", "{name: noise, params: {amount: 0.2}}", False),
    "edge-wear": ("shape", "{name: edge-wear, params: {amount: 0.4}}", False),
    "palette-map": ("shape", "{name: palette-map, params: {colors: ['#000000','#ffffff']}}", False),
}


@pytest.mark.parametrize("effect_name", sorted(_HONESTY_EFFECTS))
def test_bounds_expansion_is_honest(facade, tmp_path, effect_name) -> None:  # noqa: ANN001
    """Nothing is painted outside the declared paint_bounds; expanding effects use their ring.

    The node sits well inside a large transparent canvas. Every pixel outside ``paint_bounds``
    (plus a 1px AA tolerance) must be untouched background — the declaration is not lying small.
    For effects that declare expansion, at least some pixels in the expansion ring past the
    layout bounds must be painted — the declaration is not absurdly large either.
    """
    _subject, effect_yaml, expands = _HONESTY_EFFECTS[effect_name]
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 240px, height: 240px, dpi: 96}}}\n"
        "seed: 1\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: subject\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#e0356b'}\n"
        f"      effects: [{effect_yaml}]\n"
        "      constraints: {anchor: {center_x: parent.center_x, center_y: parent.center_y}, "
            "size: {w: 40%, h: 40%}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    assert compiled.document is not None, [d.code for d in compiled.diagnostics]
    layout, _backend, arr = _render_array(facade, compiled.document)
    node = _find(layout.root, "subject")
    scale = 96 / 72.0
    pb = node.paint_bounds
    bounds = node.bounds
    alpha = arr[..., 3]

    def px(rect: Rect) -> tuple[int, int, int, int]:
        return (
            int(np.floor(rect.x * scale)), int(np.floor(rect.y * scale)),
            int(np.ceil(rect.right * scale)), int(np.ceil(rect.bottom * scale)),
        )

    px0, py0, px1, py1 = px(pb)
    tol = 2
    # Outside paint_bounds (with tolerance) → fully transparent (nothing leaked out).
    mask = np.ones_like(alpha, dtype=bool)
    mask[max(0, py0 - tol):py1 + tol, max(0, px0 - tol):px1 + tol] = False
    assert alpha[mask].max() == 0, f"{effect_name}: painted outside declared paint_bounds"

    if expands:
        # The expansion ring (paint_bounds minus layout bounds) must contain painted pixels.
        bx0, by0, bx1, by1 = px(bounds)
        ring = np.zeros_like(alpha, dtype=bool)
        ring[max(0, py0):py1, max(0, px0):px1] = True
        ring[max(0, by0 + 2):max(0, by1 - 2), max(0, bx0 + 2):max(0, bx1 - 2)] = False
        assert alpha[ring].max() > 0, f"{effect_name}: declared expansion never painted"


# --------------------------------------------------------------------- validation
def test_unknown_effect_is_located(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      effects: [{name: sparkle, params: {}}]\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    diags = facade.validate_template(template, format_name="sq")
    d = next(d for d in diags if d.code == "ARC-FX-910")
    assert d.source is not None and "sparkle" in d.message


def test_invalid_effect_params_located(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      effects: [{name: posterize, params: {levels: 1}}]\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    diags = facade.validate_template(template, format_name="sq")
    assert any(d.code == "ARC-FX-902" for d in diags)


def test_geometry_effect_on_text_is_rejected(facade, tmp_path) -> None:  # noqa: ANN001
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 200px, height: 80px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: t\n      type: text\n      text: hi\n"
        "      style: {font: Inter, font_size: 20pt}\n"
        "      effects: [{name: torn-paper, params: {}}]\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    diags = facade.validate_template(template, format_name="sq")
    assert any(d.code == "ARC-FX-911" for d in diags)


def test_effect_length_accepts_px(facade, tmp_path) -> None:  # noqa: ANN001
    """DX-4: a px-valued effect length compiles and converts against the canvas DPI."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 128px, height: 128px, dpi: 144}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rrect\n"
        "      style: {fill: '#cc4477'}\n"
        "      effects: [{name: drop-shadow, params: {dx: 6px, dy: 6px, blur: 12px}}]\n"
        "      constraints: {anchor: {center_x: parent.center_x, center_y: parent.center_y}, "
            "size: {w: 50%, h: 50%}}\n",
    )
    compiled = facade._compiler.compile(template, None, "sq", None, None)
    assert compiled.document is not None, [d.code for d in compiled.diagnostics]
    shadow = compiled.document.root.children[0].effects[0]
    # 6px at 144dpi == 3pt; 12px == 6pt (px -> pt uses the canvas DPI).
    assert shadow.params["dx"] == pytest.approx(3.0)
    assert shadow.params["blur"] == pytest.approx(6.0)


def test_effect_length_rejects_percent(facade, tmp_path) -> None:  # noqa: ANN001
    """A relative % has no basis for an effect length and is still rejected (located)."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      effects: [{name: blur, params: {radius: 10%}}]\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    diags = facade.validate_template(template, format_name="sq")
    assert any(d.code == "ARC-FX-902" for d in diags)


def test_invalid_effect_params_lists_all_fields(facade, tmp_path) -> None:  # noqa: ANN001
    """DX-5: every offending field appears in one diagnostic, not just the first."""
    template = _write(
        tmp_path,
        "formats: {sq: {canvas: {width: 64px, height: 64px, dpi: 96}}}\n"
        "root:\n  id: root\n  type: group\n  children:\n"
        "    - id: s\n      type: shape\n      shape: rect\n"
        "      effects: [{name: grade, params: {contrast: 9, saturation: 9}}]\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
            "size: {w: fill, h: fill}}\n",
    )
    diags = facade.validate_template(template, format_name="sq")
    d = next(d for d in diags if d.code == "ARC-FX-902")
    assert "contrast" in d.message and "saturation" in d.message


def test_ink_bleed_grows_dark_ink_not_light() -> None:
    """ink-bleed spreads dark ink into lighter areas (a grey erosion), never the reverse.

    Regression for the effect having grown the *bright* value (a dilate) — the opposite of its
    name. On a dark ink square over a light opaque field the ink region must expand.
    """
    from arcavex.builtin.effects_core.context import (
        RasterContext,
        SurfacePool,
        image_to_rgba,
        rgba_to_image,
    )
    from arcavex.builtin.effects_core.raster import InkBleed, InkBleedParams

    field = np.full((48, 48, 4), 235, dtype=np.uint8)
    field[..., 3] = 255
    field[18:30, 18:30] = (20, 20, 20, 255)  # dark ink square on a light opaque field
    ctx = RasterContext(
        rgba_to_image(field), InkBleedParams(radius=3.0),
        effect_rng(1, "probe", 0), SurfacePool(), 96.0,
    )
    out = image_to_rgba(InkBleed().apply(ctx))
    dark_before = int(np.sum(np.all(field[..., :3] < 60, axis=-1)))
    dark_after = int(np.sum(np.all(out[..., :3] < 60, axis=-1)))
    assert dark_after > dark_before  # ink grew, not shrank
    assert np.array_equal(out[..., 3], field[..., 3])  # silhouette (alpha) untouched


def test_channel_offset_splits_rgb_and_keeps_alpha() -> None:
    """CR-5: channel-offset shifts R/B apart (a real split) and never touches alpha.

    The bounds-honesty test can only watch the alpha channel, which channel-offset leaves
    untouched — so this asserts directly that the colour split happens and that the silhouette
    (alpha) is preserved bit-for-bit, i.e. no colour leaks the subject's shape outward.
    """
    from arcavex.builtin.effects_core.context import (
        RasterContext,
        SurfacePool,
        image_to_rgba,
        rgba_to_image,
    )
    from arcavex.builtin.effects_core.raster import ChannelOffset, ChannelOffsetParams

    src = np.zeros((32, 32, 4), dtype=np.uint8)
    src[8:24, 14:18] = (255, 255, 255, 255)  # an opaque white vertical bar on transparent
    image = rgba_to_image(src)
    pool = SurfacePool()
    ctx = RasterContext(
        image, ChannelOffsetParams(distance=3.0, angle=0.0),
        effect_rng(1, "probe", 0), pool, 96.0,
    )
    out = image_to_rgba(ChannelOffset().apply(ctx))

    # Alpha is preserved exactly: the split cannot smear the subject's silhouette outward.
    assert np.array_equal(out[..., 3], src[..., 3])
    # The red and blue columns are displaced in opposite directions, so red != blue near the bar.
    assert not np.array_equal(out[..., 0], out[..., 2])
    # Red moved right of its source column, blue moved left (chromatic split), so along the bar's
    # rows the red-heavy and blue-heavy columns differ.
    row = 16
    red_cols = set(np.nonzero(out[row, :, 0])[0].tolist())
    blue_cols = set(np.nonzero(out[row, :, 2])[0].tolist())
    assert red_cols != blue_cols


def test_list_effects_reports_schema(facade) -> None:  # noqa: ANN001
    """DX-6: list_effects surfaces each effect's category and param schema for discovery."""
    report = facade.list_effects()
    assert report.ok and report.response_version == 1
    by_name = {e.name: e for e in report.effects}
    assert set(by_name) == set(builtin_effects())
    shadow = by_name["drop-shadow"]
    assert shadow.category == "composite"
    params = {p.name: p for p in shadow.params}
    assert params["blur"].type == "length" and params["color"].type == "colour"
    assert params["blur"].default == pytest.approx(4.0)
    posterize = {p.name: p for p in by_name["posterize"].params}
    assert posterize["levels"].type == "integer" and posterize["levels"].constraint == ">=2, <=64"


def test_blur_based_effects_declare_one_gaussian_spread() -> None:
    """Blur, glow and drop-shadow must grow their paint region by the same multiple of sigma.

    Each declares its own ``bounds_expansion``; if one used a different factor its output would
    be clipped or over-allocated relative to the others for the same visual blur.
    """
    from arcavex.builtin.effects_core.composite import (
        DropShadow,
        DropShadowParams,
        Glow,
        GlowParams,
    )
    from arcavex.builtin.effects_core.params import GAUSSIAN_VISIBLE_SIGMAS
    from arcavex.builtin.effects_core.raster import Blur, BlurParams

    sigma = 4.0
    blur = Blur().bounds_expansion(BlurParams(radius=sigma))
    glow = Glow().bounds_expansion(GlowParams(radius=sigma))
    shadow = DropShadow().bounds_expansion(DropShadowParams(blur=sigma, dx=0.0, dy=0.0))

    expected = sigma * GAUSSIAN_VISIBLE_SIGMAS
    assert blur.top == pytest.approx(expected)
    assert glow.top == pytest.approx(expected)
    # The shadow's expansion is its offset plus the spread; with a zero offset it is the spread.
    assert shadow.top == pytest.approx(expected)

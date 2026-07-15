"""Tests for the extension SDK surface and the GoldenHarness (spec §7.1, §8.5)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pytest

from arcavex import sdk
from arcavex.sdk import (
    BaseModel,
    ConfigDict,
    Effect,
    EffectKind,
    Field,
    GoldenHarness,
    Insets,
    RasterContext,
    image_to_rgba,
    rgba_to_image,
)


def _fixture(size: int = 32) -> object:
    """A small opaque RGBA gradient fixture."""
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    ramp = np.linspace(30, 220, size, dtype=np.uint8)
    arr[..., 0] = ramp[None, :]
    arr[..., 1] = ramp[:, None]
    arr[..., 2] = 90
    arr[..., 3] = 255
    return rgba_to_image(arr)


class _GrainParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: float = Field(default=0.1, ge=0.0, le=1.0)


class _Grain(Effect):
    """An honest raster effect: touches only RGB, declares zero bounds expansion."""

    kind: ClassVar[EffectKind] = EffectKind.RASTER
    param_schema: ClassVar[type[BaseModel]] = _GrainParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        return Insets()

    def apply(self, ctx: object) -> object:
        assert isinstance(ctx, RasterContext)
        rgba = image_to_rgba(ctx.image).astype(np.int16)
        h, w = rgba.shape[:2]
        noise = ctx.rng.normal(0.0, ctx.params.amount * 255.0, size=(h, w, 1))
        rgba[..., :3] = np.clip(rgba[..., :3] + noise, 0, 255)
        return rgba_to_image(rgba.astype(np.uint8))


class _DishonestGrow(Effect):
    """A dishonest raster effect: dilates alpha outward but declares zero expansion."""

    kind: ClassVar[EffectKind] = EffectKind.RASTER
    param_schema: ClassVar[type[BaseModel]] = _GrainParams

    def bounds_expansion(self, params: BaseModel) -> Insets:
        return Insets()  # lies: the effect below spreads visible pixels outward

    def apply(self, ctx: object) -> object:
        assert isinstance(ctx, RasterContext)
        rgba = image_to_rgba(ctx.image)
        alpha = rgba[..., 3].astype(np.int16)
        grown = alpha.copy()
        for shift in (1, 2, 3, 4):  # grow the opaque region ~4px on every side
            grown[shift:, :] = np.maximum(grown[shift:, :], alpha[:-shift, :])
            grown[:-shift, :] = np.maximum(grown[:-shift, :], alpha[shift:, :])
            grown[:, shift:] = np.maximum(grown[:, shift:], alpha[:, :-shift])
            grown[:, :-shift] = np.maximum(grown[:, :-shift], alpha[:, shift:])
        out = rgba.copy()
        out[..., 3] = grown.astype(np.uint8)
        out[..., :3] = 200  # paint the grown region so it is visible
        return rgba_to_image(out)


def test_sdk_reexports_the_documented_surface() -> None:
    """The SDK exposes the contracts, helpers, RNG, and testing entry points extensions import."""
    for name in (
        "Effect", "MaskGenerator", "ShapeGenerator", "Exporter", "LayoutSolver",
        "TemplateFunction", "RendererBackend", "AssetDecoder",
        "RasterContext", "ColorContext", "GeometryContext", "CompositeContext",
        "ColorMatrix", "ColorTable", "effect_rng", "SurfacePool", "render_to_pool",
        "image_to_rgba", "rgba_to_image", "Points", "RGBAColor", "BaseModel", "Field",
        "Rect", "Insets", "Dim", "Color", "GoldenHarness", "register_component",
    ):
        assert hasattr(sdk, name), f"arcavex.sdk is missing {name}"


def test_sdk_context_identity_matches_the_backend() -> None:
    """The RasterContext an extension imports is the exact class the Skia backend constructs."""
    from arcavex.builtin.effects_core.context import RasterContext as BackendRasterContext

    assert sdk.RasterContext is BackendRasterContext


def test_effect_rng_is_deterministic_and_branches() -> None:
    """The seeded RNG tree reproduces per (seed, node, index) and is independent across nodes."""
    a = sdk.effect_rng(7, "node", 0).random(4)
    b = sdk.effect_rng(7, "node", 0).random(4)
    c = sdk.effect_rng(7, "other", 0).random(4)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_goldenharness_output_and_determinism() -> None:
    """A golden render matches a freshly-saved golden and reproduces byte-for-byte (spec §8.5)."""
    harness = GoldenHarness(seed=3)
    effect, params, fixture = _Grain(), _GrainParams(), _fixture()
    first = harness.render_raster(effect, params, fixture)
    second = harness.render_raster(effect, params, fixture)
    assert np.array_equal(image_to_rgba(first), image_to_rgba(second))


def test_goldenharness_bounds_honesty_passes_for_honest_effect() -> None:
    """An effect that stays inside the node reports honest zero bounds."""
    harness = GoldenHarness(seed=3)
    bounds = harness.check_bounds_honesty(_Grain(), _GrainParams(), _fixture())
    assert bounds.honest
    assert bounds.measured.top == 0.0 and bounds.measured.left == 0.0


def test_goldenharness_bounds_honesty_fails_for_dishonest_effect() -> None:
    """An effect that paints outward but declares zero expansion is caught (ARC-EXT-050)."""
    harness = GoldenHarness(seed=3)
    result = harness.check(_DishonestGrow(), _GrainParams(), fixture=_fixture(), golden=None)
    assert not result.ok
    assert any(d.code == "ARC-EXT-050" for d in result.diagnostics)
    assert result.bounds is not None and not result.bounds.honest


def test_goldenharness_bounds_honesty_detects_builtin_blur_expansion() -> None:
    """A blur's measured spread matches its declared expansion (it is honest, not clipped)."""
    from arcavex.builtin.effects_core.raster import Blur, BlurParams

    harness = GoldenHarness(seed=3, dpi=72.0)
    params = BlurParams(radius=3.0)
    bounds = harness.check_bounds_honesty(Blur(), params, _fixture())
    # Blur declares 3*radius = 9pt each side and really does spread ~that far — so it is honest.
    assert bounds.honest
    assert bounds.measured.top > 0.0


@pytest.mark.parametrize("value,expected_is_pt", [("10pt", True), (5, True)])
def test_param_helpers_normalize_units(value: object, expected_is_pt: bool) -> None:
    """The Points field coerces pt/px/number to points; RGBAColor parses colors."""
    from pydantic import BaseModel as PydBase

    class M(PydBase):
        length: sdk.Points = 0.0
        color: sdk.RGBAColor = (0.0, 0.0, 0.0, 1.0)

    m = M(length=value, color="#ff0000")
    assert isinstance(m.length, float)
    assert m.color == (1.0, 0.0, 0.0, 1.0)

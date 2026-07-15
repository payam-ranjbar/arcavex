"""GoldenHarness — render an effect against fixtures and check output + bounds honesty.

An extension ships golden fixtures and this harness drives them (spec §7.1, §8.5). It does two
things a plain equality test cannot:

1. **Output check** — render the effect on an input fixture with a fixed seed and DPI and
   compare the result to a stored golden image, so a code change that alters pixels is caught.
2. **Bounds-expansion honesty** — a raster effect must declare, via ``bounds_expansion``, how
   far outward it paints so the layout solver can pre-grow the paint region (spec §3.2, §4.4).
   The harness renders the effect into a generously padded canvas, measures how far the *visible*
   output actually spreads beyond the input content, and compares that to the declaration. An
   effect that paints wider than it declares would be clipped in the real pipeline — that is the
   dishonesty this catches. Gross over-declaration (wasted margin) is reported as a note, not a
   failure.

The harness needs Skia and numpy, so it lives in the SDK rather than the pure kernel. It is
determinism-only tooling: it does not, and does not claim to, contain a malicious effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import skia  # type: ignore[import-untyped]

from arcavex.kernel.contracts.spi import Effect
from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.kernel.ir.units import Insets, px_to_pt
from arcavex.sdk.rng import effect_rng
from arcavex.sdk.surface import SurfacePool, image_to_rgba, rgba_to_image

# Tolerances for the honesty comparison, in points. AA and pixel rounding make an exact match
# unrealistic, so a declaration within ``_UNDER_TOL_PT`` of the measured spread is honest; only a
# larger shortfall is a clipping bug. Over-declaration beyond ``_OVER_TOL_PT`` is a note.
_UNDER_TOL_PT = 2.0
_OVER_TOL_PT = 8.0


@dataclass(frozen=True)
class BoundsHonesty:
    """The outcome of the bounds-expansion honesty check for one raster effect."""

    honest: bool
    declared: Insets
    measured: Insets
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoldenResult:
    """The combined outcome of a GoldenHarness run: pixels + bounds honesty."""

    ok: bool
    output_matches: bool | None
    max_abs_diff: int
    bounds: BoundsHonesty | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_png(path: Path) -> skia.Image:
    """Decode a PNG into a Skia image (used for fixtures and goldens)."""
    data = skia.Data.MakeFromFileName(str(path))
    if data is None:
        raise FileNotFoundError(f"golden fixture not found: {path}")
    image = skia.Image.MakeFromEncoded(data)
    if image is None:
        raise ValueError(f"could not decode PNG fixture: {path}")
    return image


def save_png(image: skia.Image, path: Path) -> None:
    """Encode a Skia image to a PNG file (used to (re)generate goldens)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = image.encodeToData(skia.EncodedImageFormat.kPNG, 100)
    path.write_bytes(bytes(data))


class GoldenHarness:
    """Drives an effect against fixtures with a fixed seed, checking output and bounds honesty.

    All randomness flows through the same seeded per-(node, effect index) generator the renderer
    uses (:func:`arcavex.sdk.rng.effect_rng`), so a harness run reproduces the real pipeline's
    bytes for a given seed.
    """

    def __init__(self, *, seed: int = 0, node_id: str = "harness", dpi: float = 72.0) -> None:
        """Bind the deterministic inputs a run replays.

        Args:
            seed: The document seed the per-effect RNG branches from.
            node_id: The node id folded into the RNG (any stable string).
            dpi: The canvas DPI point<->pixel conversions use.
        """
        self._seed = seed
        self._node_id = node_id
        self._dpi = dpi

    def render_raster(
        self, effect: Effect, params_obj: object, image: skia.Image, *, index: int = 0
    ) -> skia.Image:
        """Apply a raster effect to ``image`` and return the result, mirroring the backend.

        Builds the same :class:`~arcavex.sdk.context.RasterContext` the Skia backend builds —
        seeded RNG, a fresh surface pool, the harness DPI — so the output is byte-identical to a
        real render of the same input at the same seed.
        """
        from arcavex.sdk.context import RasterContext

        pool = SurfacePool()
        rng = effect_rng(self._seed, self._node_id, index)
        ctx = RasterContext(image, params_obj, rng, pool, self._dpi)
        result = effect.apply(ctx)
        if pool.outstanding != 0:  # pragma: no cover - a leak is an authoring bug in the effect
            raise AssertionError(
                f"effect left {pool.outstanding} pooled surface(s) unreleased"
            )
        return result

    def check_bounds_honesty(
        self, effect: Effect, params_obj: object, content: skia.Image, *, index: int = 0
    ) -> BoundsHonesty:
        """Measure how far the effect visibly paints and compare it to its declaration.

        Places ``content`` inside a generously padded transparent canvas, applies the effect, and
        measures the outward extent of the visible (non-transparent) output beyond the content
        rectangle. Under-declaration on any side (the effect paints wider than declared, so the
        real pipeline would clip it) is dishonest; gross over-declaration is a note.
        """
        declared = effect.bounds_expansion(_as_model(params_obj))
        pad_px = self._probe_pad_px(declared)
        padded, inner = _pad_content(content, pad_px)
        rendered = self.render_raster(effect, params_obj, padded, index=index)
        measured = _measured_expansion(rendered, inner, self._dpi)
        notes: list[str] = []
        honest = True
        for side in ("top", "right", "bottom", "left"):
            dec = getattr(declared, side)
            meas = getattr(measured, side)
            if meas > dec + _UNDER_TOL_PT:
                honest = False
                notes.append(
                    f"{side}: paints ~{meas:.1f}pt but declares {dec:.1f}pt "
                    "(under-declared — output would be clipped)"
                )
            elif dec > meas + _OVER_TOL_PT:
                notes.append(
                    f"{side}: declares {dec:.1f}pt but paints ~{meas:.1f}pt (over-declared)"
                )
        return BoundsHonesty(honest=honest, declared=declared, measured=measured, notes=notes)

    def check(
        self,
        effect: Effect,
        params_obj: object,
        *,
        fixture: skia.Image,
        golden: Path | None,
        index: int = 0,
        tolerance: int = 0,
        check_bounds: bool = True,
    ) -> GoldenResult:
        """Render the effect on ``fixture`` and check output against ``golden`` plus bounds honesty.

        Args:
            effect: The effect under test.
            params_obj: A validated params model instance for the effect.
            fixture: The input image the effect is applied to.
            golden: Path to the expected output PNG; ``None`` skips the pixel check (bounds only).
            index: The effect's authored index (seeds the RNG, as in the pipeline).
            tolerance: Maximum allowed per-channel absolute difference from the golden (0 = exact).
            check_bounds: Whether to also run the bounds-expansion honesty check.

        Returns:
            A :class:`GoldenResult` with located ARC-EXT diagnostics for any failure.
        """
        diagnostics: list[Diagnostic] = []
        notes: list[str] = []
        rendered = self.render_raster(effect, params_obj, fixture, index=index)

        output_matches: bool | None = None
        max_diff = 0
        if golden is not None:
            expected = load_png(golden)
            output_matches, max_diff = _compare(rendered, expected, tolerance)
            if not output_matches:
                diagnostics.append(
                    diagnostic(
                        "ARC-EXT-051",
                        f"Golden output mismatch (max per-channel diff {max_diff} > {tolerance})",
                        file=str(golden),
                        hint="Inspect the render; if the change is intended, regenerate the "
                        "golden with GoldenHarness.save and review the image diff.",
                    )
                )

        bounds: BoundsHonesty | None = None
        if check_bounds:
            bounds = self.check_bounds_honesty(effect, params_obj, fixture, index=index)
            notes.extend(bounds.notes)
            if not bounds.honest:
                diagnostics.append(
                    diagnostic(
                        "ARC-EXT-050",
                        "Effect paints outside its declared bounds_expansion: "
                        + "; ".join(bounds.notes),
                        hint="Grow bounds_expansion to cover the effect's real outward spread so "
                        "the layout solver reserves enough paint region and the output is not "
                        "clipped.",
                    )
                )

        ok = not any(d.is_error() for d in diagnostics)
        return GoldenResult(
            ok=ok,
            output_matches=output_matches,
            max_abs_diff=max_diff,
            bounds=bounds,
            diagnostics=diagnostics,
            notes=notes,
        )

    def save(
        self,
        effect: Effect,
        params_obj: object,
        fixture: skia.Image,
        golden: Path,
        *,
        index: int = 0,
    ) -> None:
        """Render and write the golden image — the one-time (re)generation path for an extension."""
        rendered = self.render_raster(effect, params_obj, fixture, index=index)
        save_png(rendered, golden)

    def _probe_pad_px(self, declared: Insets) -> int:
        """Choose a transparent probe margin generous enough not to clip the effect's spread."""
        biggest_pt = max(declared.top, declared.right, declared.bottom, declared.left, 0.0)
        biggest_px = biggest_pt * self._dpi / 72.0
        return max(24, int(round(biggest_px * 2)) + 8)


def _as_model(params_obj: object):  # noqa: ANN202 - a pydantic BaseModel, typed loosely for reuse
    """Return the params object (bounds_expansion is typed against pydantic BaseModel)."""
    return params_obj  # type: ignore[return-value]


def _pad_content(content: skia.Image, pad_px: int) -> tuple[skia.Image, tuple[int, int, int, int]]:
    """Return ``content`` centered in a transparent canvas padded by ``pad_px`` on every side.

    Also returns the inner content rectangle ``(x0, y0, x1, y1)`` in pixels.
    """
    src = image_to_rgba(content)
    h, w = src.shape[:2]
    out = np.zeros((h + 2 * pad_px, w + 2 * pad_px, 4), dtype=np.uint8)
    out[pad_px:pad_px + h, pad_px:pad_px + w, :] = src
    return rgba_to_image(out), (pad_px, pad_px, pad_px + w, pad_px + h)


def _measured_expansion(
    rendered: skia.Image, inner: tuple[int, int, int, int], dpi: float
) -> Insets:
    """Measure how far the visible (alpha>0) output extends beyond the inner content rect."""
    arr = image_to_rgba(rendered)
    alpha = arr[..., 3]
    rows = np.where(alpha.any(axis=1))[0]
    cols = np.where(alpha.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return Insets()  # nothing painted — no expansion
    top_px = max(0, inner[1] - int(rows[0]))
    left_px = max(0, inner[0] - int(cols[0]))
    bottom_px = max(0, int(rows[-1]) + 1 - inner[3])
    right_px = max(0, int(cols[-1]) + 1 - inner[2])
    return Insets(
        top=px_to_pt(top_px, dpi),
        right=px_to_pt(right_px, dpi),
        bottom=px_to_pt(bottom_px, dpi),
        left=px_to_pt(left_px, dpi),
    )


def _compare(rendered: skia.Image, expected: skia.Image, tolerance: int) -> tuple[bool, int]:
    """Return ``(matches, max_abs_diff)`` comparing two images per channel within ``tolerance``.

    Colour under a fully transparent pixel is invisible and is not preserved through a PNG
    round-trip (the encoder discards RGB where alpha is zero), so the comparison ignores RGB where
    *both* images are transparent and always compares alpha. This keeps goldens for effects on
    images with transparent regions stable without weakening the visible-pixel check.
    """
    a = image_to_rgba(rendered).astype(np.int16)
    b = image_to_rgba(expected).astype(np.int16)
    if a.shape != b.shape:
        return False, 255
    if a.size == 0:
        return True, 0
    visible = (a[..., 3] > 0) | (b[..., 3] > 0)
    rgb_diff = np.abs(a[..., :3] - b[..., :3]) * visible[..., None]
    alpha_diff = np.abs(a[..., 3] - b[..., 3])
    max_diff = int(max(rgb_diff.max(), alpha_diff.max()))
    return max_diff <= tolerance, max_diff


__all__ = [
    "BoundsHonesty",
    "GoldenHarness",
    "GoldenResult",
    "load_png",
    "save_png",
]

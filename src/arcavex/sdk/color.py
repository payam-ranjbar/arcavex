"""Color-transform values a ``COLOR`` effect returns (spec §3.2, §4.4).

A color effect is pure — params in, transform out — and returns one of these. The renderer
fuses consecutive matrices into one and composes the run into a single color filter it applies
in one pass, which is what makes the color category's fusion promise honest. These types carry
no Skia handle (they are plain data), so they live in the SDK for extension authors to build.
"""

from __future__ import annotations

from dataclasses import dataclass

# Rec.709 luminance weights, used by any luminance-based color effect (duotone, grade sat).
LUMA = (0.2126, 0.7152, 0.0722)


@dataclass(frozen=True)
class ColorMatrix:
    """A 4x5 row-major color matrix applied to **unpremultiplied** RGBA in [0, 1].

    Row ``i`` is ``[m0..m3, m4]`` so ``out_i = m0*r + m1*g + m2*b + m3*a + m4``. This is the
    exact form Skia's ``ColorFilters.Matrix`` consumes; Skia unpremultiplies before applying
    and repremultiplies after (spec §3.1.3), so effect authors reason in straight alpha.
    Consecutive matrices are *fused* by the renderer into one matrix (real associative
    composition), which is what makes the color category's fusion promise honest.
    """

    m: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.m) != 20:
            raise ValueError("a color matrix has exactly 20 entries (4x5, row-major)")


@dataclass(frozen=True)
class ColorTable:
    """A per-channel 256-entry lookup applied independently to A, R, G, B (unpremultiplied).

    Non-linear color effects (threshold, posterize) that cannot be a matrix become a table.
    A table breaks a matrix fusion run but still composes into the single color filter the
    renderer applies in one pass.
    """

    a: tuple[int, ...]
    r: tuple[int, ...]
    g: tuple[int, ...]
    b: tuple[int, ...]


# A color effect returns one of these; the renderer fuses/composes them (see the backend).
ColorTransform = ColorMatrix | ColorTable

IDENTITY_MATRIX = ColorMatrix(
    (1.0, 0.0, 0.0, 0.0, 0.0,
     0.0, 1.0, 0.0, 0.0, 0.0,
     0.0, 0.0, 1.0, 0.0, 0.0,
     0.0, 0.0, 0.0, 1.0, 0.0)
)


def compose_color_matrices(first: ColorMatrix, second: ColorMatrix) -> ColorMatrix:
    """Return the matrix applying ``first`` then ``second`` (real associative composition).

    Each 4x5 matrix is treated as a 5x5 affine with implicit last row ``[0,0,0,0,1]`` acting on
    ``(r, g, b, a, 1)``; the product ``second @ first`` collapses two passes into one. This is
    the arithmetic behind color-effect fusion, so a fused chain is provably identical to
    applying its members in sequence (spec §4.4).
    """
    a = _to_5x5(first.m)
    b = _to_5x5(second.m)
    out = [[sum(b[i][k] * a[k][j] for k in range(5)) for j in range(5)] for i in range(5)]
    flat: list[float] = []
    for i in range(4):
        flat.extend(out[i])
    return ColorMatrix(tuple(flat))


def _to_5x5(m: tuple[float, ...]) -> list[list[float]]:
    rows = [list(m[i * 5:i * 5 + 5]) for i in range(4)]
    rows.append([0.0, 0.0, 0.0, 0.0, 1.0])
    return rows


__all__ = [
    "IDENTITY_MATRIX",
    "LUMA",
    "ColorMatrix",
    "ColorTable",
    "ColorTransform",
    "compose_color_matrices",
]

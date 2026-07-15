"""Golden-image harness: perceptual (SSIM) diff, per-platform sets, and failure dumps.

Rendering is compared perceptually, not byte-for-byte, because sub-pixel anti-aliasing differs
across platforms (spec §8.5 asks for ``dssim <= 0.003`` on per-platform golden sets). We
compute **structural dissimilarity** (DSSIM = (1 - SSIM) / 2) with an 11×11 Gaussian-windowed
SSIM in pure numpy — no scipy/skimage dependency. The threshold below maps directly to the
spec's ``dssim <= 0.003`` intent (SSIM >= 0.994).

Goldens live under ``tests/golden/goldens/<platform-tag>/`` so a Linux and a Windows set never
collide. Regenerate with ``ARCAVEX_UPDATE_GOLDENS=1`` (Makefile target ``golden-update``); a
mismatch dumps the actual image, the expected image, and an amplified diff heatmap into
``outputs-tmp/golden-failures/`` for review.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

import numpy as np
import skia  # type: ignore[import-untyped]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLDEN_ROOT = Path(__file__).resolve().parent / "goldens"
_FAILURE_DIR = _REPO_ROOT / "outputs-tmp" / "golden-failures"

# SSIM >= 0.994  <=>  DSSIM = (1 - SSIM)/2 <= 0.003, the spec's §8.5 perceptual budget. A little
# headroom is left implicitly by comparing against per-platform goldens (same renderer, same
# fonts), so real regressions (a broken effect, a shifted node) blow well past 0.003 while
# benign AA jitter stays far under it.
DSSIM_THRESHOLD = 0.003


def platform_tag() -> str:
    """Return the per-platform golden directory tag, e.g. ``win-x86_64``."""
    system = {"windows": "win", "darwin": "macos", "linux": "linux"}.get(
        platform.system().lower(), platform.system().lower()
    )
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine, machine
    )
    return f"{system}-{machine}"


def golden_dir() -> Path:
    """Return this platform's golden directory (created on demand)."""
    d = _GOLDEN_ROOT / platform_tag()
    d.mkdir(parents=True, exist_ok=True)
    return d


def updating() -> bool:
    """Whether goldens are being regenerated (``ARCAVEX_UPDATE_GOLDENS=1``)."""
    return os.environ.get("ARCAVEX_UPDATE_GOLDENS") == "1"


def surface_to_array(surface: skia.Surface) -> np.ndarray:
    """Return an ``(H, W, 4)`` uint8 straight-alpha RGBA array of a rendered surface."""
    image = surface.makeImageSnapshot()
    return image.toarray(
        colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
    )


def load_png(path: Path) -> np.ndarray:
    """Load a PNG into an ``(H, W, 4)`` uint8 straight-alpha RGBA array."""
    image = skia.Image.open(str(path))
    return image.toarray(
        colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
    )


def save_png(array: np.ndarray, path: Path) -> None:
    """Write an ``(H, W, 4)`` uint8 RGBA array to ``path`` as a PNG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    contiguous = np.ascontiguousarray(array, dtype=np.uint8)
    skia.Image.fromarray(contiguous, colorType=skia.kRGBA_8888_ColorType).save(
        str(path), skia.kPNG
    )


def _to_gray(array: np.ndarray) -> np.ndarray:
    """Composite RGBA over black and return a float luminance image in [0, 1]."""
    rgb = array[..., :3].astype(np.float64) / 255.0
    alpha = array[..., 3:4].astype(np.float64) / 255.0
    premul = rgb * alpha  # deterministic handling of transparent pixels (over black)
    return premul @ np.array([0.2126, 0.7152, 0.0722])


def _gaussian_kernel(size: int = 11, sigma: float = 1.5) -> np.ndarray:
    ax = np.arange(size) - size // 2
    k = np.exp(-(ax**2) / (2 * sigma**2))
    return k / k.sum()


def _blur(img: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Separable Gaussian blur (reflect padding); loops over taps, not pixels."""
    radius = len(kernel) // 2
    padded = np.pad(img, ((0, 0), (radius, radius)), mode="reflect")
    out = np.zeros_like(img)
    for i, w in enumerate(kernel):
        out += w * padded[:, i : i + img.shape[1]]
    padded = np.pad(out, ((radius, radius), (0, 0)), mode="reflect")
    out2 = np.zeros_like(img)
    for i, w in enumerate(kernel):
        out2 += w * padded[i : i + img.shape[0], :]
    return out2


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Return the mean structural similarity of two RGBA images in [0, 1] (1.0 = identical)."""
    x, y = _to_gray(a), _to_gray(b)
    kernel = _gaussian_kernel()
    c1, c2 = 0.01**2, 0.03**2
    mu_x, mu_y = _blur(x, kernel), _blur(y, kernel)
    mu_x2, mu_y2, mu_xy = mu_x**2, mu_y**2, mu_x * mu_y
    sigma_x2 = _blur(x * x, kernel) - mu_x2
    sigma_y2 = _blur(y * y, kernel) - mu_y2
    sigma_xy = _blur(x * y, kernel) - mu_xy
    numerator = (2 * mu_xy + c1) * (2 * sigma_xy + c2)
    denominator = (mu_x2 + mu_y2 + c1) * (sigma_x2 + sigma_y2 + c2)
    return float(np.clip(numerator / denominator, 0.0, 1.0).mean())


def dssim(a: np.ndarray, b: np.ndarray) -> float:
    """Return the structural dissimilarity DSSIM = (1 - SSIM) / 2 (0.0 = identical)."""
    return (1.0 - ssim(a, b)) / 2.0


def compare_to_golden(name: str, actual: np.ndarray) -> None:
    """Assert ``actual`` matches golden ``name`` within the DSSIM budget.

    Under ``ARCAVEX_UPDATE_GOLDENS=1`` the golden is (re)written and the check passes. A missing
    golden without update mode fails with an instruction. On a real mismatch the actual,
    expected, and an amplified diff heatmap are dumped for review, then the test fails.
    """
    golden_path = golden_dir() / f"{name}.png"
    if updating():
        save_png(actual, golden_path)
        return
    assert golden_path.is_file(), (
        f"missing golden {golden_path}; run with ARCAVEX_UPDATE_GOLDENS=1 to create it"
    )
    expected = load_png(golden_path)
    if expected.shape != actual.shape:
        _dump_failure(name, actual, expected)
        raise AssertionError(
            f"golden {name}: shape {actual.shape} != expected {expected.shape}"
        )
    score = dssim(actual, expected)
    if score > DSSIM_THRESHOLD:
        _dump_failure(name, actual, expected)
        raise AssertionError(
            f"golden {name}: dssim {score:.5f} exceeds {DSSIM_THRESHOLD} "
            f"(artifacts in {_FAILURE_DIR})"
        )


def _dump_failure(name: str, actual: np.ndarray, expected: np.ndarray) -> None:
    _FAILURE_DIR.mkdir(parents=True, exist_ok=True)
    save_png(actual, _FAILURE_DIR / f"{name}.actual.png")
    save_png(expected, _FAILURE_DIR / f"{name}.expected.png")
    if actual.shape == expected.shape:
        diff = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
        heat = np.clip(diff[..., :3].sum(axis=2) * 4, 0, 255).astype(np.uint8)
        heatmap = np.dstack(
            [heat, np.zeros_like(heat), 255 - heat, np.full_like(heat, 255)]
        )
        save_png(heatmap, _FAILURE_DIR / f"{name}.diff.png")

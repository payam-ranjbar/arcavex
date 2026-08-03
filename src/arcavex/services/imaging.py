"""Perceptual image comparison for ``arcavex diff`` (spec §5.3).

``diff`` reports both an exact byte comparison and a perceptual one. The perceptual score is
DSSIM = (1 − SSIM) / 2 computed with an 11×11 Gaussian-windowed SSIM in pure numpy — the same
metric and window the golden-image test harness uses (§8.5), kept here in the service layer so
the CLI can report it without importing test code. Zero means pixel-identical.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import skia  # type: ignore[import-untyped]

# SSIM parameters from Wang et al. 2004, the values the metric is defined with: an 11x11
# Gaussian window at sigma 1.5, and stabilizers K1/K2 that keep the ratio finite where the local
# mean or variance approaches zero. tests/golden/harness.py uses the same values, so a score
# here and a golden comparison are the same measurement.
_SSIM_WINDOW = 11
_SSIM_SIGMA = 1.5
_SSIM_K1 = 0.01
_SSIM_K2 = 0.03


def _load(path: Path) -> np.ndarray:
    image = skia.Image.open(str(path))
    return image.toarray(
        colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType
    )


def _to_gray(array: np.ndarray) -> np.ndarray:
    rgb = array[..., :3].astype(np.float64) / 255.0
    alpha = array[..., 3:4].astype(np.float64) / 255.0
    premul = rgb * alpha
    return premul @ np.array([0.2126, 0.7152, 0.0722])


def _gaussian_kernel(size: int = _SSIM_WINDOW, sigma: float = _SSIM_SIGMA) -> np.ndarray:
    ax = np.arange(size) - size // 2
    k = np.exp(-(ax**2) / (2 * sigma**2))
    return k / k.sum()


def _blur(img: np.ndarray, kernel: np.ndarray) -> np.ndarray:
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


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    x, y = _to_gray(a), _to_gray(b)
    kernel = _gaussian_kernel()
    c1, c2 = _SSIM_K1**2, _SSIM_K2**2
    mu_x, mu_y = _blur(x, kernel), _blur(y, kernel)
    mu_x2, mu_y2, mu_xy = mu_x**2, mu_y**2, mu_x * mu_y
    sigma_x2 = _blur(x * x, kernel) - mu_x2
    sigma_y2 = _blur(y * y, kernel) - mu_y2
    sigma_xy = _blur(x * y, kernel) - mu_xy
    numerator = (2 * mu_xy + c1) * (2 * sigma_xy + c2)
    denominator = (mu_x2 + mu_y2 + c1) * (sigma_x2 + sigma_y2 + c2)
    return float(np.clip(numerator / denominator, 0.0, 1.0).mean())


def dssim_files(a: Path, b: Path) -> float | None:
    """Return the DSSIM of two PNGs, or ``None`` when their pixel dimensions differ.

    Differing dimensions are a structural change the metadata diff reports separately; there is
    no meaningful windowed SSIM between mismatched shapes, so the perceptual score is ``None``.
    """
    ia, ib = _load(a), _load(b)
    if ia.shape != ib.shape:
        return None
    return (1.0 - _ssim(ia, ib)) / 2.0

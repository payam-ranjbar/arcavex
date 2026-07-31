"""Golden test for this effect, run by ``arcavex ext test`` (or directly).

Builds an in-memory fixture and asserts three things the harness is designed to catch:
1. determinism — the same seed produces byte-identical output on a rerun (spec §3.2);
2. golden output — the render matches the committed ``golden/archive-print.png`` once you create it;
3. bounds-expansion honesty — the effect does not paint outside its declared ``bounds_expansion``.

The scaffold ships no golden image yet, so ``ext test`` passes on determinism + bounds honesty
until you commit one. Create/regenerate it with ``python golden_test.py --update`` after the look
settles, then review the image diff before committing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from arcavex.sdk import GoldenHarness, image_to_rgba, rgba_to_image

from component import ArchivePrint, ArchivePrintParams

_HERE = Path(__file__).resolve().parent
_GOLDEN = _HERE / "golden" / "archive-print.png"
_SEED = 7


def _fixture() -> object:
    """A 48x48 RGBA gradient with an opaque centre — enough content to exercise the effect."""
    arr = np.zeros((48, 48, 4), dtype=np.uint8)
    ramp = np.linspace(40, 220, 48, dtype=np.uint8)
    arr[..., 0] = ramp[None, :]
    arr[..., 1] = ramp[:, None]
    arr[..., 2] = 128
    arr[8:40, 8:40, 3] = 255
    return rgba_to_image(arr)


def main(update: bool = False) -> int:
    effect = ArchivePrint()
    params = ArchivePrintParams(
        levels=4,
        screen=0.12,
        texture=0.04,
        accent_strength=0.6,
        misregister="2pt",
        scan_pitch="5pt",
    )
    harness = GoldenHarness(seed=_SEED)
    fixture = _fixture()

    if update:
        harness.save(effect, params, fixture, _GOLDEN)
        print(f"wrote golden {_GOLDEN}")
        return 0

    first = harness.render_raster(effect, params, fixture)
    second = harness.render_raster(effect, params, fixture)
    if not np.array_equal(image_to_rgba(first), image_to_rgba(second)):
        print("FAIL: effect is not deterministic for a fixed seed")
        return 1

    golden = _GOLDEN if _GOLDEN.exists() else None
    result = harness.check(effect, params, fixture=fixture, golden=golden)
    for note in result.notes:
        print("note:", note)
    if not result.ok:
        for diag in result.diagnostics:
            print(f"FAIL: {diag.code}: {diag.message}")
        return 1
    if golden is None:
        print(
            "OK: deterministic and bounds-honest "
            "(no committed golden yet — run 'python golden_test.py --update' to add one)"
        )
    else:
        print("OK: deterministic, matches golden, and bounds-honest")
    return 0


if __name__ == "__main__":
    sys.exit(main(update="--update" in sys.argv[1:]))

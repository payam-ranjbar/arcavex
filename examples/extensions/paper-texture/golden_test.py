"""Golden test for the paper-texture effect. Run by ``arcavex ext test`` (and directly).

Checks three things with the SDK's :class:`GoldenHarness`:

1. **Determinism** — a fixed seed renders byte-identical output on a rerun (spec §3.2).
2. **Golden output** — the render matches the committed ``golden/paper-texture.png`` exactly.
3. **Bounds-expansion honesty** — the effect does not paint outside its declared
   ``bounds_expansion`` (it declares zero and stays inside, so this must hold).

Exits non-zero on any failure so ``arcavex ext test`` reports it. Regenerate the golden with
``python golden_test.py --update`` after an intended change and review the image diff.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from arcavex.sdk import GoldenHarness, image_to_rgba, load_png

from component import PaperTexture, PaperTextureParams

_HERE = Path(__file__).resolve().parent
_FIXTURE = _HERE / "fixtures" / "input.png"
_GOLDEN = _HERE / "golden" / "paper-texture.png"
_SEED = 1234
_PARAMS = PaperTextureParams(grain=0.06, fibre=0.10, warmth=0.08)


def main(update: bool = False) -> int:
    effect = PaperTexture()
    harness = GoldenHarness(seed=_SEED)
    fixture = load_png(_FIXTURE)

    if update:
        harness.save(effect, _PARAMS, fixture, _GOLDEN)
        print(f"wrote golden {_GOLDEN}")
        return 0

    first = harness.render_raster(effect, _PARAMS, fixture)
    second = harness.render_raster(effect, _PARAMS, fixture)
    if not np.array_equal(image_to_rgba(first), image_to_rgba(second)):
        print("FAIL: effect is not deterministic for a fixed seed")
        return 1

    result = harness.check(effect, _PARAMS, fixture=fixture, golden=_GOLDEN)
    for note in result.notes:
        print("note:", note)
    if not result.ok:
        for diag in result.diagnostics:
            print(f"FAIL: {diag.code}: {diag.message}")
        return 1
    print("OK: deterministic, matches golden, and bounds-honest")
    return 0


if __name__ == "__main__":
    sys.exit(main(update="--update" in sys.argv[1:]))

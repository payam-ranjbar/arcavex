"""Golden and determinism checks for every Graphic Style Lab effect."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from arcavex.sdk import GoldenHarness, image_to_rgba, rgba_to_image

from component import (
    CinemaEmulsion,
    CinemaEmulsionParams,
    RisoRegister,
    RisoRegisterParams,
    SwissCut,
    SwissCutParams,
    XeroxPulse,
    XeroxPulseParams,
)


HERE = Path(__file__).resolve().parent
CASES = (
    ("swiss-cut", SwissCut(), SwissCutParams()),
    ("xerox-pulse", XeroxPulse(), XeroxPulseParams()),
    ("cinema-emulsion", CinemaEmulsion(), CinemaEmulsionParams()),
    ("riso-register", RisoRegister(), RisoRegisterParams()),
)


def fixture() -> object:
    yy, xx = np.indices((96, 128), dtype=np.float32)
    arr = np.zeros((96, 128, 4), dtype=np.uint8)
    arr[..., 0] = np.clip(35 + xx * 1.55, 0, 255).astype(np.uint8)
    arr[..., 1] = np.clip(28 + yy * 2.1, 0, 255).astype(np.uint8)
    arr[..., 2] = np.clip(200 - xx * 0.72 + yy * 0.25, 0, 255).astype(np.uint8)
    circle = (xx - 78) ** 2 + (yy - 42) ** 2 < 24 ** 2
    arr[circle, :3] = (232, 188, 96)
    arr[..., 3] = 255
    return rgba_to_image(arr)


def main(update: bool = False) -> int:
    ok = True
    for index, (name, effect, params) in enumerate(CASES):
        harness = GoldenHarness(seed=19 + index)
        source = fixture()
        golden = HERE / "golden" / f"{name}.png"
        if update:
            harness.save(effect, params, source, golden)
            print(f"wrote {golden}")
            continue
        first = harness.render_raster(effect, params, source)
        second = harness.render_raster(effect, params, source)
        deterministic = np.array_equal(image_to_rgba(first), image_to_rgba(second))
        result = harness.check(effect, params, fixture=source, golden=golden if golden.exists() else None)
        if not deterministic or not result.ok:
            ok = False
            print(f"FAIL {name}: deterministic={deterministic} harness={result.ok}")
            for diagnostic in result.diagnostics:
                print(f"  {diagnostic.code}: {diagnostic.message}")
        else:
            print(f"OK {name}: deterministic, golden-matched, bounds-honest")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(update="--update" in sys.argv[1:]))

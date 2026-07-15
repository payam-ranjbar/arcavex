"""Scaffolding for ``arcavex ext scaffold <kind> <target>`` (spec §7.2).

Writes a complete, immediately-valid extension directory: an ``extension.toml`` manifest, an
entry module implementing the chosen contract against the SDK, a ``golden_test.py`` that ``ext
test`` runs, and a README. The scaffolded component is a real, minimal, deterministic
implementation — it validates and tests green out of the box so an author starts from a working
extension and edits inward, rather than debugging a stub.
"""

from __future__ import annotations

import re

from arcavex.sdk.registration import COMPONENT_KINDS

_ENGINE_MIN = "0.1"
_IR_MIN = "1.0"


def class_name_for(name: str) -> str:
    """Turn a component name into a CamelCase class name (``paper-texture`` -> ``PaperTexture``)."""
    parts = re.split(r"[-_]+", name)
    return "".join(part.capitalize() for part in parts if part) or "Component"


def _manifest(name: str, kind: str, class_name: str) -> str:
    return (
        f'name = "{name}"\n'
        'version = "0.1.0"\n'
        f'ir_min = "{_IR_MIN}"\n'
        f'engine_min = "{_ENGINE_MIN}"\n'
        "\n"
        "[[components]]\n"
        f'kind = "{kind}"\n'
        f'name = "{name}"\n'
        f'entry = "component:{class_name}"\n'
    )


def _effect_module(class_name: str) -> str:
    return f'''"""A scaffolded raster effect. Edit the params and numpy pass; keep it deterministic.

Import only ``arcavex.sdk`` — it re-exports every contract, helper, and IR value type an
extension may use. Any randomness must come from ``ctx.rng`` (the seeded per-effect generator),
never from ``random`` or the clock, so the same inputs always produce the same bytes.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from arcavex.sdk import (
    BaseModel,
    ConfigDict,
    Effect,
    EffectKind,
    Field,
    Insets,
    RasterContext,
    image_to_rgba,
    rgba_to_image,
)


class {class_name}Params(BaseModel):
    """Parameters for the effect. ``amount`` scales the seeded grain in [0, 1]."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: float = Field(default=0.08, ge=0.0, le=1.0)


class {class_name}(Effect):
    """Overlay seeded monochrome grain on the node raster (a paper-texture starter)."""

    kind: ClassVar[EffectKind] = EffectKind.RASTER
    param_schema: ClassVar[type[BaseModel]] = {class_name}Params

    def bounds_expansion(self, params: BaseModel) -> Insets:
        """Stays inside the node — declares no outward paint (honest zero expansion)."""
        return Insets()

    def apply(self, ctx: object) -> object:
        """Return the raster with seeded grain added to RGB; alpha is left untouched."""
        assert isinstance(ctx, RasterContext)
        params = ctx.params
        assert isinstance(params, {class_name}Params)
        rgba = image_to_rgba(ctx.image).astype(np.int16)
        h, w = rgba.shape[:2]
        grain = ctx.rng.normal(0.0, params.amount * 255.0, size=(h, w, 1))
        rgba[..., :3] = np.clip(rgba[..., :3] + grain, 0, 255)
        return rgba_to_image(rgba.astype(np.uint8))
'''


def _mask_module(name: str, class_name: str) -> str:
    return f'''"""A scaffolded mask generator. Edit the params and the path construction.

Import only ``arcavex.sdk``. A mask builds a clip path in the node's point-space bounds; the
renderer clips the node's content to it.
"""

from __future__ import annotations

from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.sdk import BaseModel, ConfigDict, Field, MaskGenerator, Points, Rect


class {class_name}Params(BaseModel):
    """Parameters for the mask. ``inset`` shrinks the clip rectangle by a point margin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    inset: Points = Field(default=0.0, ge=0.0)


class {class_name}(MaskGenerator):
    """Clip to the node bounds inset by a fixed point margin (a starter mask)."""

    name: ClassVar[str] = "{name}"
    param_schema: ClassVar[type[BaseModel]] = {class_name}Params

    def build(self, params: BaseModel, bounds: Rect) -> skia.Path:
        """Build the clip path within ``bounds``."""
        assert isinstance(params, {class_name}Params)
        m = min(params.inset, bounds.w / 2.0, bounds.h / 2.0)
        path = skia.Path()
        path.addRect(
            skia.Rect.MakeXYWH(bounds.x + m, bounds.y + m, bounds.w - 2 * m, bounds.h - 2 * m)
        )
        return path
'''


def _generic_module(name: str, kind: str, class_name: str, contract: str) -> str:
    return f'''"""A scaffolded {kind} component. Implement the {contract} contract (arcavex.sdk)."""

from __future__ import annotations

from typing import ClassVar

from arcavex.sdk import {contract}


class {class_name}({contract}):
    """TODO: implement the {contract} contract. Import only arcavex.sdk."""

    name: ClassVar[str] = "{name}"
'''


def _effect_golden_test(class_name: str) -> str:
    return f'''"""Golden test for this effect, run by ``arcavex ext test`` (or directly).

Builds an in-memory fixture and asserts two things the harness is designed to catch:
1. determinism — the same seed produces byte-identical output on a rerun;
2. bounds-expansion honesty — the effect does not paint outside its declared ``bounds_expansion``.

Add a committed golden image (see GoldenHarness.save / GoldenHarness.check) once the look settles.
"""

from __future__ import annotations

import sys

import numpy as np

from arcavex.sdk import GoldenHarness, image_to_rgba, rgba_to_image

from component import {class_name}, {class_name}Params


def _fixture() -> object:
    """A 48x48 RGBA gradient with an opaque centre — enough content to exercise the effect."""
    arr = np.zeros((48, 48, 4), dtype=np.uint8)
    ramp = np.linspace(40, 220, 48, dtype=np.uint8)
    arr[..., 0] = ramp[None, :]
    arr[..., 1] = ramp[:, None]
    arr[..., 2] = 128
    arr[8:40, 8:40, 3] = 255
    return rgba_to_image(arr)


def main() -> int:
    effect = {class_name}()
    params = {class_name}Params()
    harness = GoldenHarness(seed=7)
    fixture = _fixture()

    first = harness.render_raster(effect, params, fixture)
    second = harness.render_raster(effect, params, fixture)
    if not np.array_equal(image_to_rgba(first), image_to_rgba(second)):
        print("FAIL: effect is not deterministic for a fixed seed")
        return 1

    result = harness.check(effect, params, fixture=fixture, golden=None)
    for note in result.notes:
        print("note:", note)
    if not result.ok:
        for diag in result.diagnostics:
            print(f"FAIL: {{diag.code}}: {{diag.message}}")
        return 1
    print("OK: deterministic and bounds-honest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _readme(name: str, kind: str) -> str:
    return f"""# {name}

A scaffolded Arcavex {kind} extension (trusted local code — review it like any dependency).

## Workflow

```
arcavex ext validate .
arcavex ext test .
arcavex ext add .
arcavex ext enable {name}
```

Then use the component from a template (a `{kind}` named `{name}`) and render as usual. Disabling
takes effect on the next run; the loader registers only enabled extensions at start.

## Files

- `extension.toml` — the manifest (name, version, engine/IR floors, component list).
- `component.py` — the implementation. Import only `arcavex.sdk`.
- `golden_test.py` — the check `arcavex ext test` runs (determinism + bounds honesty).
"""


def scaffold_files(name: str, kind: str) -> dict[str, str]:
    """Return the filename -> contents map for a scaffolded extension of ``kind``.

    ``kind`` must be a known component keyword. Effect and mask kinds get a working reference
    implementation and a golden test; other kinds get a minimal contract stub.
    """
    class_name = class_name_for(name)
    contract = COMPONENT_KINDS[kind].contract.__name__
    files: dict[str, str] = {
        "extension.toml": _manifest(name, kind, class_name),
        "README.md": _readme(name, kind),
    }
    if kind == "effect":
        files["component.py"] = _effect_module(class_name)
        files["golden_test.py"] = _effect_golden_test(class_name)
    elif kind == "mask":
        files["component.py"] = _mask_module(name, class_name)
    else:
        files["component.py"] = _generic_module(name, kind, class_name, contract)
    return files


__all__ = ["class_name_for", "scaffold_files"]

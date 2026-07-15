"""Scaffolding for ``arcavex ext scaffold <kind> <target>`` (spec §7.2).

Writes a complete, immediately-valid extension directory for **every** component kind: an
``extension.toml`` manifest, an entry module implementing the chosen contract against the SDK
with a minimal working body, a ``golden_test.py`` that ``ext test`` runs, and a README. The
scaffolded component is a real, minimal, deterministic implementation — it validates and tests
green out of the box so an author starts from a working extension and edits inward, rather than
debugging a stub.

The ``backend`` and ``layout_solver`` kinds consume/produce the whole-document IR
(:class:`~arcavex.sdk.LayoutDocument`); their starters are genuinely valid and testable but are
forward-looking — v1 selects the built-in ``skia`` backend and ``anchors`` solver, so a custom
one registers like any component but is not yet selectable from a template.
"""

from __future__ import annotations

import re
from collections.abc import Callable

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


# --------------------------------------------------------------------------- effect
def _effect_module(name: str, class_name: str) -> str:
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


def _effect_golden_test(name: str, class_name: str) -> str:
    return f'''"""Golden test for this effect, run by ``arcavex ext test`` (or directly).

Builds an in-memory fixture and asserts three things the harness is designed to catch:
1. determinism — the same seed produces byte-identical output on a rerun (spec §3.2);
2. golden output — the render matches the committed ``golden/{name}.png`` once you create it;
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

from component import {class_name}, {class_name}Params

_HERE = Path(__file__).resolve().parent
_GOLDEN = _HERE / "golden" / "{name}.png"
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
    effect = {class_name}()
    params = {class_name}Params()
    harness = GoldenHarness(seed=_SEED)
    fixture = _fixture()

    if update:
        harness.save(effect, params, fixture, _GOLDEN)
        print(f"wrote golden {{_GOLDEN}}")
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
            print(f"FAIL: {{diag.code}}: {{diag.message}}")
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
'''


# --------------------------------------------------------------------------- mask
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


def _mask_golden_test(name: str, class_name: str) -> str:
    return f'''"""Golden test for this mask, run by ``arcavex ext test`` (or directly).

Builds the clip path in a fixed rectangle and asserts it is non-empty and deterministic (the same
params and bounds serialize byte-identically), so a mask that silently changes shape is caught.
"""

from __future__ import annotations

import sys

from arcavex.sdk import Rect

from component import {class_name}, {class_name}Params


def main() -> int:
    mask = {class_name}()
    params = {class_name}Params()
    bounds = Rect(0.0, 0.0, 100.0, 100.0)

    first = mask.build(params, bounds)
    if first.isEmpty():
        print("FAIL: mask produced an empty clip path")
        return 1
    second = mask.build(params, bounds)
    if bytes(first.serialize()) != bytes(second.serialize()):
        print("FAIL: mask is not deterministic for the same params and bounds")
        return 1
    print("OK: mask builds a deterministic, non-empty clip path")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# --------------------------------------------------------------------------- shape
def _shape_module(name: str, class_name: str) -> str:
    return f'''"""A scaffolded shape generator. Edit the params and the path construction.

Import only ``arcavex.sdk``. A shape builds a path in the node's point-space bounds; the renderer
fills or strokes it like any shape.
"""

from __future__ import annotations

import math
from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.sdk import BaseModel, ConfigDict, Field, Rect, ShapeGenerator


class {class_name}Params(BaseModel):
    """Parameters for the shape. ``sides`` is the number of vertices of the polygon."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sides: int = Field(default=6, ge=3, le=64)


class {class_name}(ShapeGenerator):
    """A regular polygon inscribed in the node bounds (a starter shape)."""

    name: ClassVar[str] = "{name}"
    param_schema: ClassVar[type[BaseModel]] = {class_name}Params

    def build(self, params: BaseModel, bounds: Rect) -> skia.Path:
        """Build the polygon path centred in ``bounds``."""
        assert isinstance(params, {class_name}Params)
        cx, cy = bounds.center_x, bounds.center_y
        radius = min(bounds.w, bounds.h) / 2.0
        path = skia.Path()
        for i in range(params.sides):
            angle = -math.pi / 2.0 + i * 2.0 * math.pi / params.sides
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.close()
        return path
'''


def _shape_golden_test(name: str, class_name: str) -> str:
    return f'''"""Golden test for this shape, run by ``arcavex ext test`` (or directly).

Builds the shape in a fixed rectangle and asserts it is non-empty and deterministic (the same
params and bounds serialize byte-identically), so a shape that silently changes is caught.
"""

from __future__ import annotations

import sys

from arcavex.sdk import Rect

from component import {class_name}, {class_name}Params


def main() -> int:
    shape = {class_name}()
    params = {class_name}Params()
    bounds = Rect(0.0, 0.0, 100.0, 100.0)

    first = shape.build(params, bounds)
    if first.isEmpty():
        print("FAIL: shape produced an empty path")
        return 1
    second = shape.build(params, bounds)
    if bytes(first.serialize()) != bytes(second.serialize()):
        print("FAIL: shape is not deterministic for the same params and bounds")
        return 1
    print("OK: shape builds a deterministic, non-empty path")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# --------------------------------------------------------------------------- exporter
def _exporter_module(name: str, class_name: str) -> str:
    return f'''"""A scaffolded exporter. Edit the encoding; change the declared ``format`` to match.

Import only ``arcavex.sdk``. An exporter encodes a rendered surface to bytes and writes them to
the target path, returning an ``ExportReport`` with the byte count and content hash. This starter
encodes PNG under the declared format name.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.sdk import ExportOptions, ExportReport, Exporter, Surface


class {class_name}(Exporter):
    """Encode a rendered surface to a file (a PNG-encoding starter)."""

    format: ClassVar[str] = "{name}"

    def export(self, surface: Surface, target: Path, opts: ExportOptions) -> ExportReport:
        """Encode ``surface`` and write it to ``target``, returning a report."""
        image = surface.makeImageSnapshot()
        payload = bytes(image.encodeToData(skia.EncodedImageFormat.kPNG, opts.quality))
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return ExportReport(
            path=str(target),
            format=self.format,
            bytes_written=len(payload),
            content_sha256=hashlib.sha256(payload).hexdigest(),
        )
'''


def _exporter_golden_test(name: str, class_name: str) -> str:
    return f'''"""Golden test for this exporter, run by ``arcavex ext test`` (or directly).

Renders a small deterministic surface, exports it to a temporary file, and asserts the export
wrote bytes and is deterministic (two exports of the same surface report the same content hash).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import skia  # type: ignore[import-untyped]

from arcavex.sdk import ExportOptions

from component import {class_name}


def _surface() -> object:
    """A 32x32 surface with a fixed fill — enough to exercise the encoder deterministically."""
    surface = skia.Surface(32, 32)
    with surface as canvas:
        canvas.clear(skia.Color4f(0.1, 0.4, 0.7, 1.0))
    return surface


def main() -> int:
    exporter = {class_name}()
    opts = ExportOptions()
    out_dir = Path(tempfile.mkdtemp(prefix="arcavex-ext-test-"))
    target = out_dir / f"out.{{exporter.format}}"

    first = exporter.export(_surface(), target, opts)
    if first.bytes_written <= 0:
        print("FAIL: exporter wrote no bytes")
        return 1
    second = exporter.export(_surface(), target, opts)
    if first.content_sha256 != second.content_sha256:
        print("FAIL: exporter is not deterministic for the same surface")
        return 1
    print(f"OK: exporter wrote {{first.bytes_written}} bytes deterministically")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# --------------------------------------------------------------------- template_function
def _template_function_module(name: str, class_name: str) -> str:
    return f'''"""A scaffolded template function. Edit ``call`` to compute your value.

Import only ``arcavex.sdk``. A template function is pure and deterministic — no I/O, no clock, no
randomness — so an expression that calls it always evaluates the same way.
"""

from __future__ import annotations

from typing import ClassVar

from arcavex.sdk import TemplateFunction, Value


class {class_name}(TemplateFunction):
    """Repeat a string ``n`` times (a pure, deterministic starter)."""

    name: ClassVar[str] = "{name}"

    def call(self, *args: Value) -> Value:
        """Evaluate the function. ``call(text, n)`` returns ``text`` repeated ``n`` times."""
        text = str(args[0]) if args else ""
        count = int(args[1]) if len(args) > 1 else 1  # type: ignore[arg-type]
        return text * max(count, 0)
'''


def _template_function_golden_test(name: str, class_name: str) -> str:
    return f'''"""Golden test for this template function, run by ``arcavex ext test`` (or directly).

Calls the function with sample arguments and asserts it returns the expected value and is
deterministic (the same arguments evaluate identically), matching the purity a template function
must have.
"""

from __future__ import annotations

import sys

from component import {class_name}


def main() -> int:
    fn = {class_name}()
    first = fn.call("ab", 3)
    second = fn.call("ab", 3)
    if first != second:
        print("FAIL: template function is not deterministic for the same arguments")
        return 1
    if first != "ababab":
        print(f"FAIL: expected 'ababab', got {{first!r}}")
        return 1
    print(f"OK: template function returned {{first!r}} deterministically")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# --------------------------------------------------------------------------- decoder
def _decoder_module(name: str, class_name: str) -> str:
    return f'''"""A scaffolded asset decoder. Edit ``decode`` to parse your media type.

Import only ``arcavex.sdk``. A decoder turns raw asset bytes into a decoded asset, enforcing the
resource guards it is handed before any expensive work. This starter records the byte length; a
real decoder parses the format and returns pixels or geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from arcavex.sdk import AssetDecoder, DecodedAsset, DecodeGuards


@dataclass(frozen=True)
class _Decoded:
    """A minimal decoded asset: the source byte count (replace with real decoded content)."""

    source_bytes: int


class {class_name}(AssetDecoder):
    """Decode raw bytes into an asset (a starter that measures the input)."""

    media_types: ClassVar[tuple[str, ...]] = ("application/octet-stream",)

    def decode(self, blob: bytes, guards: DecodeGuards) -> DecodedAsset:
        """Decode ``blob`` under ``guards`` and return the decoded asset."""
        if len(blob) > guards.max_source_bytes:
            raise ValueError(
                f"asset is {{len(blob)}} bytes, over the {{guards.max_source_bytes}}-byte guard"
            )
        return _Decoded(source_bytes=len(blob))
'''


def _decoder_golden_test(name: str, class_name: str) -> str:
    return f'''"""Golden test for this decoder, run by ``arcavex ext test`` (or directly).

Decodes a fixed byte string under default guards and asserts the decode succeeds and is
deterministic (the same bytes decode to an equal asset).
"""

from __future__ import annotations

import sys

from arcavex.sdk import DecodeGuards

from component import {class_name}


def main() -> int:
    decoder = {class_name}()
    guards = DecodeGuards()
    blob = b"arcavex-scaffold-fixture"

    first = decoder.decode(blob, guards)
    second = decoder.decode(blob, guards)
    if first != second:
        print("FAIL: decoder is not deterministic for the same bytes")
        return 1
    print(f"OK: decoder produced {{first!r}} deterministically")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# --------------------------------------------------------------------------- backend
def _backend_module(name: str, class_name: str) -> str:
    return f'''"""A scaffolded renderer backend. Edit ``render`` to paint the laid-out document.

Import only ``arcavex.sdk``. A backend renders a :class:`LayoutDocument` (every node already has
resolved bounds and an absolute transform) into a surface. This starter allocates a blank canvas
at the document's pixel size; a real backend walks ``doc.root`` and paints each node.

v1 selects the built-in ``skia`` backend for rendering; a custom backend registers like any
component but is not yet selectable from a template — it is forward-looking surface.
"""

from __future__ import annotations

from typing import ClassVar

import skia  # type: ignore[import-untyped]

from arcavex.sdk import LayoutDocument, RenderOptions, RendererBackend, Surface


class {class_name}(RendererBackend):
    """Render a laid-out document to a surface (a blank-canvas starter)."""

    name: ClassVar[str] = "{name}"

    def render(self, doc: LayoutDocument, opts: RenderOptions) -> Surface:
        """Allocate a surface at the document's pixel size and return it."""
        dpi = opts.dpi if opts.dpi is not None else doc.canvas.dpi
        width_px = max(1, round(doc.canvas.width_pt * dpi / 72.0))
        height_px = max(1, round(doc.canvas.height_pt * dpi / 72.0))
        surface = skia.Surface(width_px, height_px)
        with surface as canvas:
            canvas.clear(skia.ColorWHITE)
        return surface
'''


def _backend_golden_test(name: str, class_name: str) -> str:
    return f'''"""Golden test for this backend, run by ``arcavex ext test`` (or directly).

Builds a minimal laid-out document, renders it, and asserts the backend returns a surface and is
deterministic (two renders encode byte-identically).
"""

from __future__ import annotations

import sys

import skia  # type: ignore[import-untyped]

from arcavex.sdk import (
    LayoutDocument,
    LayoutNode,
    Matrix3,
    Rect,
    RenderOptions,
    ResolvedCanvas,
)

from component import {class_name}


def _document() -> LayoutDocument:
    """A 64x64pt @72dpi document with a single root group covering the canvas."""
    bounds = Rect(0.0, 0.0, 64.0, 64.0)
    root = LayoutNode(
        source_node_id="root",
        kind="group",
        bounds=bounds,
        absolute_transform=Matrix3.identity(),
        paint_bounds=bounds,
        render_bounds=bounds,
    )
    return LayoutDocument(
        canvas=ResolvedCanvas(width_pt=64.0, height_pt=64.0, dpi=72), seed=0, root=root
    )


def _png(surface: object) -> bytes:
    return bytes(surface.makeImageSnapshot().encodeToData(skia.EncodedImageFormat.kPNG, 100))


def main() -> int:
    backend = {class_name}()
    doc = _document()
    opts = RenderOptions()

    first = backend.render(doc, opts)
    if first is None:
        print("FAIL: backend returned no surface")
        return 1
    if _png(first) != _png(backend.render(doc, opts)):
        print("FAIL: backend is not deterministic for the same document")
        return 1
    print("OK: backend renders a deterministic surface")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# ------------------------------------------------------------------------ layout_solver
def _layout_solver_module(name: str, class_name: str) -> str:
    return f'''"""A scaffolded layout solver. Edit ``solve`` to resolve geometry for every node.

Import only ``arcavex.sdk``. A layout solver turns a compiled document (units normalized, layout
still symbolic) into a :class:`LayoutDocument` where every node has resolved bounds and an
absolute transform. This starter produces a single root node covering the canvas; a real solver
recurses into ``doc.root.children`` and resolves each node's constraints. It reads its input
document structurally (by attribute), the way every component reads the document it is handed.

v1 selects the built-in ``anchors`` solver; a custom solver registers like any component but is
not yet selectable from a template — it is forward-looking surface.
"""

from __future__ import annotations

from typing import ClassVar

from arcavex.sdk import (
    LayoutDocument,
    LayoutNode,
    LayoutSolver,
    Matrix3,
    MeasureFn,
    Rect,
    ResolvedCanvas,
)


class {class_name}(LayoutSolver):
    """Resolve a compiled document into a laid-out one (a canvas-covering starter)."""

    name: ClassVar[str] = "{name}"

    def solve(self, doc: object, measure: MeasureFn) -> LayoutDocument:
        """Resolve geometry for every node, returning a new immutable document."""
        canvas = doc.canvas  # type: ignore[attr-defined]
        bounds = Rect(0.0, 0.0, canvas.width_pt, canvas.height_pt)
        root = LayoutNode(
            source_node_id=doc.root.id,  # type: ignore[attr-defined]
            kind="group",
            bounds=bounds,
            absolute_transform=Matrix3.identity(),
            paint_bounds=bounds,
            render_bounds=bounds,
        )
        return LayoutDocument(
            canvas=ResolvedCanvas(
                width_pt=canvas.width_pt, height_pt=canvas.height_pt, dpi=canvas.dpi
            ),
            seed=doc.seed,  # type: ignore[attr-defined]
            root=root,
        )
'''


def _layout_solver_golden_test(name: str, class_name: str) -> str:
    return f'''"""Golden test for this layout solver, run by ``arcavex ext test`` (or directly).

Feeds a minimal stand-in compiled document (the solver reads it structurally) and asserts the
solver returns a laid-out document and is deterministic (two solves are equal).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from arcavex.sdk import LayoutDocument, MeasureResult

from component import {class_name}


def _measure(_request: object) -> MeasureResult:
    """A trivial measurement function (this starter solver does not call it)."""
    return MeasureResult(width_pt=0.0, height_pt=0.0, baseline_pt=0.0, line_count=0)


def _compiled() -> object:
    """A minimal compiled-document stand-in: a canvas and a root with an id."""
    return SimpleNamespace(
        seed=0,
        canvas=SimpleNamespace(width_pt=240.0, height_pt=160.0, dpi=96),
        root=SimpleNamespace(id="root"),
    )


def main() -> int:
    solver = {class_name}()
    doc = _compiled()

    first = solver.solve(doc, _measure)
    if not isinstance(first, LayoutDocument):
        print("FAIL: solver did not return a LayoutDocument")
        return 1
    second = solver.solve(doc, _measure)
    if first != second:
        print("FAIL: solver is not deterministic for the same document")
        return 1
    print("OK: solver produces a deterministic LayoutDocument")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _readme(name: str, kind: str) -> str:
    forward_looking = (
        "\n> **Note.** v1 renders with the built-in backend and layout solver, so a custom "
        f"`{kind}` registers like any component but is not yet selectable from a template — it is "
        "forward-looking surface you can validate and test today.\n"
        if kind in {"backend", "layout_solver"}
        else ""
    )
    golden = (
        "\n## Regenerating the golden\n\n"
        "After an intentional change to the look, regenerate the committed golden image and "
        "review the diff before committing:\n\n"
        "```\npython golden_test.py --update\n```\n"
        if kind == "effect"
        else ""
    )
    return f"""# {name}

A scaffolded Arcavex {kind} extension (trusted local code — review it like any dependency).
{forward_looking}
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
- `golden_test.py` — the check `arcavex ext test` runs (determinism + contract behaviour).
{golden}"""


# One builder pair per kind: (component.py source, golden_test.py source), both taking
# ``(name, class_name)``. Every kind ships a working component and a golden test, so ``ext
# validate`` and ``ext test`` pass on a fresh scaffold of any kind.
_MODULES: dict[str, tuple[Callable[[str, str], str], Callable[[str, str], str]]] = {
    "effect": (_effect_module, _effect_golden_test),
    "mask": (_mask_module, _mask_golden_test),
    "shape": (_shape_module, _shape_golden_test),
    "exporter": (_exporter_module, _exporter_golden_test),
    "template_function": (_template_function_module, _template_function_golden_test),
    "decoder": (_decoder_module, _decoder_golden_test),
    "backend": (_backend_module, _backend_golden_test),
    "layout_solver": (_layout_solver_module, _layout_solver_golden_test),
}


def scaffold_files(name: str, kind: str) -> dict[str, str]:
    """Return the filename -> contents map for a scaffolded extension of ``kind``.

    ``kind`` must be a known component keyword. Every kind gets a real, minimal, deterministic
    implementation and a matching ``golden_test.py`` so the scaffold validates and tests green
    out of the box.
    """
    class_name = class_name_for(name)
    module_builder, golden_builder = _MODULES[kind]
    return {
        "extension.toml": _manifest(name, kind, class_name),
        "README.md": _readme(name, kind),
        "component.py": module_builder(name, class_name),
        "golden_test.py": golden_builder(name, class_name),
    }


# Every documented kind has a working builder — keep this in lockstep with COMPONENT_KINDS so a
# newly-added kind cannot silently ship without a scaffold.
assert set(_MODULES) == set(COMPONENT_KINDS), "scaffold builders must cover every component kind"


__all__ = ["class_name_for", "scaffold_files"]

"""Draw the Arcavex Desktop application mark so the packaged icon set is reproducible.

Run this, then regenerate the platform icon set:

    uv run python scripts/generate_desktop_icon.py
    cd apps/desktop && npx tauri icon src-tauri/icons/source.png
"""

from __future__ import annotations

from pathlib import Path

import skia

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ICON = ROOT / "apps" / "desktop" / "src-tauri" / "icons" / "source.png"

SIZE = 1024
CORNER_RADIUS = 224.0
BACKGROUND = 0xFF0E1116
ACCENT_TOP = 0xFF6FB1FC
ACCENT_BOTTOM = 0xFF2F6FD0
STROKE_WIDTH = 96.0


def _draw(canvas: skia.Canvas) -> None:
    """Paint a dark plate carrying one accent chevron over a swept arc."""
    plate = skia.RRect.MakeRectXY(skia.Rect.MakeWH(SIZE, SIZE), CORNER_RADIUS, CORNER_RADIUS)
    canvas.drawRRect(plate, skia.Paint(Color=BACKGROUND, AntiAlias=True))

    accent = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=STROKE_WIDTH,
        StrokeCap=skia.Paint.kRound_Cap,
        StrokeJoin=skia.Paint.kRound_Join,
        Shader=skia.GradientShader.MakeLinear(
            points=[(0.0, 0.0), (0.0, float(SIZE))],
            colors=[ACCENT_TOP, ACCENT_BOTTOM],
        ),
    )

    chevron = skia.Path()
    chevron.moveTo(320.0, 596.0)
    chevron.lineTo(512.0, 272.0)
    chevron.lineTo(704.0, 596.0)
    canvas.drawPath(chevron, accent)

    # The sweep sits clear of the chevron so the mark reads as an arc under a vertex.
    sweep = skia.Path()
    sweep.addArc(skia.Rect.MakeLTRB(268.0, 508.0, 756.0, 844.0), 25.0, 130.0)
    canvas.drawPath(sweep, accent)


def main() -> int:
    """Render the mark at full resolution and write it as the icon source of truth."""
    surface = skia.Surface(SIZE, SIZE)
    with surface as canvas:
        _draw(canvas)
    image = surface.makeImageSnapshot()
    data = image.encodeToData(skia.EncodedImageFormat.kPNG, 100)
    if data is None:
        raise RuntimeError(f"could not encode {SOURCE_ICON}")
    SOURCE_ICON.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_ICON.write_bytes(bytes(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

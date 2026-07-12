"""SkParagraph text service: font database, measurement, and paint helpers.

This is the single source of truth for shaping and metrics (spec §4.3). The font database
is built once from bundled fonts (``library-seed/fonts`` in dev, plus ``$ARCAVEX_HOME/fonts``)
and registered as the *default* font manager so every fallback lookup is confined to bundled
fonts — system fonts are never consulted, which is what determinism requires. A single shared
``skia.Unicode`` instance backs every paragraph build.

Base paragraph direction is controlled with Unicode BiDi isolates (U+2067 RLI / U+2069 PDI)
because the skia-python 144 binding exposes no ``setTextDirection`` (see ADR 0001).
"""

from __future__ import annotations

import os
from pathlib import Path

import skia  # type: ignore[import-untyped]

from arcavex.kernel.contracts.types import MeasureRequest, MeasureResult

_RLI = "⁧"  # RIGHT-TO-LEFT ISOLATE
_PDI = "⁩"  # POP DIRECTIONAL ISOLATE

_UNBOUNDED_WIDTH = 1.0e7


def find_font_dirs() -> list[Path]:
    """Return the ordered list of directories to load bundled fonts from.

    The in-repo ``library-seed/fonts`` directory (located by walking up to the
    ``pyproject.toml`` marker) comes first, followed by ``$ARCAVEX_HOME/fonts`` when set.
    System font directories are never included.
    """
    dirs: list[Path] = []
    marker = _find_repo_root()
    if marker is not None:
        seed = marker / "library-seed" / "fonts"
        if seed.is_dir():
            dirs.append(seed)
    home = os.environ.get("ARCAVEX_HOME")
    if home:
        home_fonts = Path(home) / "fonts"
        if home_fonts.is_dir():
            dirs.append(home_fonts)
    return dirs


def _find_repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


class TextService:
    """Loads bundled fonts and measures/paints text via SkParagraph."""

    def __init__(self, font_dirs: list[Path] | None = None) -> None:
        """Build the font collection from bundled fonts.

        Args:
            font_dirs: Optional explicit font directories; defaults to
                :func:`find_font_dirs`.
        """
        self._provider = skia.textlayout.TypefaceFontProvider()
        self._families: set[str] = set()
        dirs = font_dirs if font_dirs is not None else find_font_dirs()
        for directory in dirs:
            for path in sorted(directory.glob("*.ttf")):
                typeface = skia.Typeface.MakeFromFile(str(path))
                if typeface is None:
                    continue
                self._provider.registerTypeface(typeface)
                self._families.add(typeface.getFamilyName())
        self._collection = skia.textlayout.FontCollection()
        self._collection.setDefaultFontManager(self._provider)
        self._unicode = skia.Unicode()

    @property
    def families(self) -> set[str]:
        """The set of font family names available in the bundled database."""
        return set(self._families)

    def measure(self, req: MeasureRequest) -> MeasureResult:
        """Measure text extents and baseline in points."""
        paragraph = self._build(req)
        width = req.max_width_pt if req.max_width_pt is not None else _UNBOUNDED_WIDTH
        paragraph.layout(width)
        longest = float(paragraph.LongestLine)
        height = float(paragraph.Height)
        baseline = float(paragraph.AlphabeticBaseline)
        per_line = req.font_size_pt * (req.line_height or 1.2)
        line_count = max(1, round(height / per_line)) if height > 0 and per_line > 0 else 1
        return MeasureResult(
            width_pt=longest,
            height_pt=height,
            baseline_pt=baseline,
            line_count=line_count,
        )

    def paint(
        self,
        canvas: object,
        req: MeasureRequest,
        x_pt: float,
        y_pt: float,
        width_pt: float,
        *,
        color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
        align: str = "start",
    ) -> None:
        """Lay out at ``width_pt`` and paint the paragraph at ``(x_pt, y_pt)``."""
        paragraph = self._build(req, color=color, align=align)
        paragraph.layout(width_pt)
        paragraph.paint(canvas, x_pt, y_pt)

    # ------------------------------------------------------------------ internals
    def _build(
        self,
        req: MeasureRequest,
        color: tuple[float, float, float, float] | None = None,
        align: str = "start",
    ) -> skia.textlayout.Paragraph:
        style = skia.textlayout.ParagraphStyle()
        style.setTextAlign(_resolve_align(align, req.direction))

        text_style = skia.textlayout.TextStyle()
        families = list(req.font_families) if req.font_families else ["Inter"]
        text_style.setFontFamilies(families)
        text_style.setFontSize(req.font_size_pt)
        text_style.setFontStyle(
            skia.FontStyle(
                req.font_weight,
                skia.FontStyle.kNormal_Width,
                skia.FontStyle.kItalic_Slant
                if req.italic
                else skia.FontStyle.kUpright_Slant,
            )
        )
        if color is not None:
            text_style.setColor(skia.Color4f(*color).toColor())
        else:
            text_style.setColor(skia.ColorBLACK)
        if req.letter_spacing_pt:
            text_style.setLetterSpacing(req.letter_spacing_pt)
        style.setTextStyle(text_style)

        builder = skia.textlayout.ParagraphBuilder.make(
            style, self._collection, self._unicode
        )
        text = req.text
        if req.direction == "rtl":
            text = f"{_RLI}{text}{_PDI}"
        builder.addText(text)
        return builder.Build()


def _resolve_align(align: str, direction: str) -> object:
    """Map logical/explicit alignment and base direction to a paragraph alignment."""
    tl = skia.textlayout
    if align == "left":
        return tl.TextAlign.kLeft
    if align == "right":
        return tl.TextAlign.kRight
    if align == "center":
        return tl.TextAlign.kCenter
    # logical start/end resolved by base direction
    if align == "end":
        return tl.TextAlign.kLeft if direction == "rtl" else tl.TextAlign.kRight
    return tl.TextAlign.kRight if direction == "rtl" else tl.TextAlign.kLeft

"""SkParagraph text service: font database, measurement, fit policies, and painting.

This is the single source of truth for shaping and metrics (spec §4.3). The font database
is built once from bundled fonts (``library-seed/fonts`` in dev, plus ``$ARCAVEX_HOME/fonts``)
and registered as the *default* font manager so every fallback lookup is confined to bundled
fonts — system fonts are never consulted, which is what determinism requires. A single shared
``skia.Unicode`` instance backs every paragraph build.

Base paragraph direction is controlled with Unicode BiDi isolates (U+2066 LRI / U+2067 RLI /
U+2069 PDI) because the skia-python 144 binding exposes no ``setTextDirection`` (see ADR 0001).
Fit policies (shrink_to_fit / truncate / wrap) are implemented here on top of scalar paragraph
metrics with the spec's ≤ 8 measurement iterations, since the binding exposes neither
max-lines nor an ellipsis API.
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import skia  # type: ignore[import-untyped]

from arcavex.kernel.contracts.types import MeasureRequest, MeasureResult
from arcavex.kernel.ir.models import ResolvedRun

_LRI = "⁦"  # LEFT-TO-RIGHT ISOLATE
_RLI = "⁧"  # RIGHT-TO-LEFT ISOLATE
_PDI = "⁩"  # POP DIRECTIONAL ISOLATE
_ELLIPSIS = "…"

_UNBOUNDED_WIDTH = 1.0e7
# Fit tolerance in points: shaped extents within this of the box count as fitting, so
# sub-pixel rounding never triggers a spurious overflow.
_FIT_EPS = 0.25
_MAX_FIT_ITERS = 8


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
    """Loads bundled fonts and measures/fits/paints text via SkParagraph."""

    def __init__(self, font_dirs: list[Path] | None = None) -> None:
        """Build the font collection from bundled fonts.

        Args:
            font_dirs: Optional explicit font directories; defaults to
                :func:`find_font_dirs`.
        """
        self._provider = skia.textlayout.TypefaceFontProvider()
        self._families: set[str] = set()
        # family name -> typefaces, plus a flat list, for missing-glyph probing.
        self._by_family: dict[str, list[object]] = {}
        self._all_typefaces: list[object] = []
        dirs = font_dirs if font_dirs is not None else find_font_dirs()
        for directory in dirs:
            for path in sorted(directory.glob("*.ttf")):
                typeface = skia.Typeface.MakeFromFile(str(path))
                if typeface is None:
                    continue
                self._provider.registerTypeface(typeface)
                family = typeface.getFamilyName()
                self._families.add(family)
                self._by_family.setdefault(family, []).append(typeface)
                self._all_typefaces.append(typeface)
        self._collection = skia.textlayout.FontCollection()
        self._collection.setDefaultFontManager(self._provider)
        self._unicode = skia.Unicode()

    @property
    def families(self) -> set[str]:
        """The set of font family names available in the bundled database."""
        return set(self._families)

    # ------------------------------------------------------------------ measurement
    def measure(self, req: MeasureRequest) -> MeasureResult:
        """Measure and fit text, returning extents, baseline, and the fit outcome.

        Runs the ≤ 8-iteration fit loop for ``shrink_to_fit`` / ``truncate`` and classifies the
        outcome; a plain ``wrap`` request measures once. Callers that only need intrinsic
        extents pass no ``max_width_pt``/``max_height_pt`` and get a single measurement.
        """
        runs = self._runs_of(req)
        base_size = req.font_size_pt
        missing = tuple(self.missing_glyphs(runs))
        para = self._layout(runs, req, base_size)
        w, h, lines = _metrics(para, base_size, req.line_height)
        if self._fits(req, w, h, lines):
            result = _result(w, h, para, lines, base_size, "none")
        elif req.fit_policy == "shrink_to_fit":
            result = self._shrink(req, runs, base_size)
        elif req.fit_policy == "truncate":
            result = self._truncate(req, runs, base_size)
        else:
            # wrap (default): does not fit; the solver applies the overflow policy.
            result = _result(w, h, para, lines, base_size, "overflowing")
        return result.model_copy(update={"missing_glyphs": missing})

    def _shrink(
        self, req: MeasureRequest, runs: tuple[ResolvedRun, ...], base_size: float
    ) -> MeasureResult:
        """Binary-search the largest font size in [min, base] that fits (≤ 8 iterations)."""
        min_size = req.min_size_pt if req.min_size_pt is not None else base_size
        min_size = max(1.0, min(min_size, base_size))
        # If even the smallest allowed size overflows, report non-convergence at min size.
        para_min = self._layout(runs, req, min_size)
        w, h, lines = _metrics(para_min, min_size, req.line_height)
        if not self._fits(req, w, h, lines):
            return _result(w, h, para_min, lines, min_size, "overflowing", converged=False)
        lo, hi = min_size, base_size
        best = min_size
        best_para = para_min
        best_metrics = (w, h, lines)
        for _ in range(_MAX_FIT_ITERS):
            mid = (lo + hi) / 2.0
            para = self._layout(runs, req, mid)
            mw, mh, ml = _metrics(para, mid, req.line_height)
            if self._fits(req, mw, mh, ml):
                best, best_para, best_metrics = mid, para, (mw, mh, ml)
                lo = mid
            else:
                hi = mid
            if hi - lo < 0.25:
                break
        bw, bh, bl = best_metrics
        kind = "shrunk" if best < base_size - _FIT_EPS else "none"
        return _result(bw, bh, best_para, bl, best, kind)

    def _truncate(
        self, req: MeasureRequest, runs: tuple[ResolvedRun, ...], base_size: float
    ) -> MeasureResult:
        """Binary-search the longest text prefix that fits, then append an ellipsis."""
        full = "".join(r.text for r in runs)
        normalized = _nfc(full)
        lo, hi = 0, len(normalized)
        best = ""
        best_para = self._layout_text(normalized + _ELLIPSIS, req, base_size)
        for _ in range(_MAX_FIT_ITERS):
            mid = (lo + hi) // 2
            candidate = normalized[:mid].rstrip() + _ELLIPSIS
            para = self._layout_text(candidate, req, base_size)
            w, h, lines = _metrics(para, base_size, req.line_height)
            if self._fits(req, w, h, lines):
                best, best_para = candidate, para
                lo = mid + 1
            else:
                hi = mid - 1
            if lo > hi:
                break
        w, h, lines = _metrics(best_para, base_size, req.line_height)
        return _result(
            w, h, best_para, lines, base_size, "truncated", out_text=best or _ELLIPSIS
        )

    def _fits(self, req: MeasureRequest, w: float, h: float, lines: int) -> bool:
        if req.max_width_pt is not None and w > req.max_width_pt + _FIT_EPS:
            return False
        if req.max_height_pt is not None and h > req.max_height_pt + _FIT_EPS:
            return False
        if req.max_lines is not None and lines > req.max_lines:
            return False
        return True

    # ------------------------------------------------------------------ painting
    def paint(
        self,
        canvas: object,
        req: MeasureRequest,
        x_pt: float,
        y_pt: float,
        width_pt: float,
    ) -> None:
        """Lay out at ``width_pt`` and paint the paragraph at ``(x_pt, y_pt)``."""
        runs = self._runs_of(req)
        paragraph = self._build(runs, req, req.font_size_pt)
        paragraph.layout(width_pt if width_pt > 0 else _UNBOUNDED_WIDTH)
        paragraph.paint(canvas, x_pt, y_pt)

    # ------------------------------------------------------------------ missing glyphs
    def missing_glyphs(self, runs: tuple[ResolvedRun, ...]) -> list[tuple[int, tuple[str, ...]]]:
        """Return ``(codepoint, families_tried)`` for glyphs no bundled font can render.

        Every declared family plus the full bundled set (the collection's fallback pool) is
        probed with ``unicharToGlyph``; whitespace and control characters are ignored. A
        non-empty result becomes a warning diagnostic (spec §4.3).
        """
        missing: list[tuple[int, tuple[str, ...]]] = []
        seen: set[int] = set()
        for run in runs:
            families = run.font_families or ()
            for ch in _nfc(run.text):
                cp = ord(ch)
                if cp in seen or ch.isspace() or unicodedata.category(ch).startswith("C"):
                    continue
                seen.add(cp)
                if not self._has_glyph(cp):
                    missing.append((cp, families))
        return missing

    def _has_glyph(self, codepoint: int) -> bool:
        for typeface in self._all_typefaces:
            if typeface.unicharToGlyph(codepoint) != 0:  # type: ignore[attr-defined]
                return True
        return False

    # ------------------------------------------------------------------ internals
    def _runs_of(self, req: MeasureRequest) -> tuple[ResolvedRun, ...]:
        if req.runs:
            return req.runs
        return (
            ResolvedRun(
                text=req.text,
                font_families=req.font_families or ("Inter",),
                font_size_pt=req.font_size_pt,
                font_weight=req.font_weight,
                italic=req.italic,
                color=req.color,
                letter_spacing_pt=req.letter_spacing_pt,
            ),
        )

    def _layout(
        self, runs: tuple[ResolvedRun, ...], req: MeasureRequest, size: float
    ) -> skia.textlayout.Paragraph:
        para = self._build(runs, req, size)
        para.layout(req.max_width_pt if req.max_width_pt is not None else _UNBOUNDED_WIDTH)
        return para

    def _layout_text(
        self, text: str, req: MeasureRequest, size: float
    ) -> skia.textlayout.Paragraph:
        run = ResolvedRun(
            text=text,
            font_families=req.font_families or ("Inter",),
            font_size_pt=size,
            font_weight=req.font_weight,
            italic=req.italic,
            color=req.color,
            letter_spacing_pt=req.letter_spacing_pt,
        )
        return self._layout((run,), req, size)

    def _build(
        self, runs: tuple[ResolvedRun, ...], req: MeasureRequest, size: float
    ) -> skia.textlayout.Paragraph:
        scale = size / req.font_size_pt if req.font_size_pt else 1.0
        pstyle = skia.textlayout.ParagraphStyle()
        pstyle.setTextAlign(_resolve_align(req.align, req.direction))
        base_style = self._text_style(runs[0], req, scale) if runs else None
        if base_style is not None:
            pstyle.setTextStyle(base_style)
        builder = skia.textlayout.ParagraphBuilder.make(
            pstyle, self._collection, self._unicode
        )
        if req.direction == "rtl":
            builder.addText(_RLI)
        elif req.direction == "ltr":
            builder.addText(_LRI)
        for run in runs:
            builder.pushStyle(self._text_style(run, req, scale))
            builder.addText(_nfc(run.text))
            builder.pop()
        if req.direction in {"rtl", "ltr"}:
            builder.addText(_PDI)
        return builder.Build()

    def _text_style(
        self, run: ResolvedRun, req: MeasureRequest, scale: float
    ) -> skia.textlayout.TextStyle:
        text_style = skia.textlayout.TextStyle()
        families = list(run.font_families) if run.font_families else list(
            req.font_families or ("Inter",)
        )
        text_style.setFontFamilies(families)
        text_style.setFontSize(run.font_size_pt * scale)
        text_style.setFontStyle(
            skia.FontStyle(
                run.font_weight,
                skia.FontStyle.kNormal_Width,
                skia.FontStyle.kItalic_Slant if run.italic else skia.FontStyle.kUpright_Slant,
            )
        )
        text_style.setColor(skia.Color4f(*run.color).toColor())
        spacing = run.letter_spacing_pt or req.letter_spacing_pt
        if spacing:
            text_style.setLetterSpacing(spacing)
        if req.language:
            text_style.setLocale(req.language)
        return text_style


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _metrics(
    para: skia.textlayout.Paragraph, size: float, line_height: float | None
) -> tuple[float, float, int]:
    w = float(para.LongestLine)
    h = float(para.Height)
    per_line = size * (line_height or 1.2)
    lines = max(1, round(h / per_line)) if h > 0 and per_line > 0 else 1
    return w, h, lines


def _result(
    w: float,
    h: float,
    para: skia.textlayout.Paragraph,
    lines: int,
    resolved_size: float,
    kind: str,
    *,
    out_text: str | None = None,
    converged: bool = True,
) -> MeasureResult:
    return MeasureResult(
        width_pt=w,
        height_pt=h,
        baseline_pt=float(para.AlphabeticBaseline),
        line_count=lines,
        resolved_size_pt=resolved_size,
        overflow_kind=kind,  # type: ignore[arg-type]
        out_text=out_text,
        converged=converged,
    )


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

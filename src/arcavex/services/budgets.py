"""Per-render resource budgets (spec §8.3).

Arcavex is a local tool, so the threat is not a hostile tenant but accidental runaway work — a
format that resolves to a 200 000-pixel canvas, a DPI override that asks for a 40-gigabyte
surface. These budgets bound the *render surface* the way the asset decode guards (Phase 4) bound
input images: cheap dimensions known before any pixels are allocated are checked up front, so an
oversized render is refused with a located ``ARC-RND`` diagnostic (exit 4) instead of exhausting
memory. The wall-clock budget is a post-hoc guard — Skia renders are not preemptible in v1, so it
catches a pathological render after the fact rather than interrupting it; the pixel, memory, and
dimension budgets are what actually prevent a runaway allocation.

Limits resolve through the §6.3 config chain (``[budgets]`` in ``config.toml``) over generous
built-in defaults, so a user who genuinely needs a larger surface can raise them without touching
code, and ``doctor`` can report them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic

# Generous built-in ceilings: a 30k-per-side canvas at 4 bytes/pixel is already ~3.6 GB, so the
# surface-memory budget bites first for the common "too big" mistake while leaving real print
# work (A4 @ 600 dpi ≈ 5000×7000) comfortably inside every limit.
DEFAULT_MAX_DIMENSION = 30_000
DEFAULT_MAX_PIXELS = 400_000_000
DEFAULT_MAX_SURFACE_BYTES = 2_000_000_000
DEFAULT_MAX_WALL_MS = 120_000


@dataclass(frozen=True)
class RenderBudget:
    """Resolved per-render resource ceilings."""

    max_dimension: int = DEFAULT_MAX_DIMENSION
    max_pixels: int = DEFAULT_MAX_PIXELS
    max_surface_bytes: int = DEFAULT_MAX_SURFACE_BYTES
    max_wall_ms: int = DEFAULT_MAX_WALL_MS

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> RenderBudget:
        """Build a budget from a parsed ``config.toml`` ``[budgets]`` table (tolerant of gaps)."""
        section = {}
        if isinstance(config, dict):
            raw = config.get("budgets")
            if isinstance(raw, dict):
                section = raw
        return cls(
            max_dimension=_pos_int(section.get("max_dimension"), DEFAULT_MAX_DIMENSION),
            max_pixels=_pos_int(section.get("max_pixels"), DEFAULT_MAX_PIXELS),
            max_surface_bytes=_pos_int(
                section.get("max_surface_bytes"), DEFAULT_MAX_SURFACE_BYTES
            ),
            max_wall_ms=_pos_int(section.get("max_wall_ms"), DEFAULT_MAX_WALL_MS),
        )

    def check_surface(self, width_px: int, height_px: int, *, file: str | None = None) -> None:
        """Refuse an over-budget render surface before it is allocated (raises ``ARC-RND-02x``).

        ``file`` locates the diagnostic on the template whose canvas/DPI produced the surface.
        """
        if width_px > self.max_dimension or height_px > self.max_dimension:
            raise self._error(
                "ARC-RND-020",
                f"Output dimension {width_px}×{height_px}px exceeds the "
                f"{self.max_dimension}px per-side budget",
                "Reduce the canvas size or the render DPI, or raise "
                "[budgets].max_dimension in config.toml.",
                file,
            )
        pixels = width_px * height_px
        if pixels > self.max_pixels:
            raise self._error(
                "ARC-RND-021",
                f"Render surface {width_px}×{height_px} = {pixels} pixels exceeds the "
                f"{self.max_pixels}-pixel budget",
                "Reduce the canvas size or DPI, or raise [budgets].max_pixels in config.toml.",
                file,
            )
        surface_bytes = pixels * 4
        if surface_bytes > self.max_surface_bytes:
            raise self._error(
                "ARC-RND-022",
                f"Render surface needs {surface_bytes} bytes, over the "
                f"{self.max_surface_bytes}-byte budget",
                "Reduce the canvas size or DPI, or raise [budgets].max_surface_bytes in "
                "config.toml.",
                file,
            )

    def check_wall_ms(self, elapsed_ms: float, *, file: str | None = None) -> None:
        """Raise ``ARC-RND-023`` when a completed render overran the wall-clock budget."""
        if elapsed_ms > self.max_wall_ms:
            raise self._error(
                "ARC-RND-023",
                f"Render took {elapsed_ms:.0f}ms, over the {self.max_wall_ms}ms wall-clock budget",
                "Simplify the scene or effects, or raise [budgets].max_wall_ms in config.toml.",
                file,
            )

    def _error(self, code: str, message: str, hint: str, file: str | None) -> DiagnosticError:
        kwargs: dict[str, Any] = {"hint": hint}
        if file is not None:
            kwargs["file"] = file
            kwargs["keypath"] = "canvas"
        return DiagnosticError(diagnostic(code, message, **kwargs))


def _pos_int(value: Any, default: int) -> int:
    """Coerce a config value to a positive int, falling back to ``default``."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default

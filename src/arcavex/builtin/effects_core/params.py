"""Shared pydantic field types for effect parameter schemas.

These field helpers are part of the stable extension surface and now live in
:mod:`arcavex.sdk.params`; the built-in effects re-export them from here so their imports and
the SDK stay one definition. See the SDK module for the normalization rules.
"""

from __future__ import annotations

from arcavex.sdk.params import RGBA, Points, RGBAColor

# Multiple of sigma at which a Gaussian's contribution stops being visible, and therefore the
# factor every blur-based effect grows its paint region by in ``bounds_expansion``. Under-
# declaring clips the blur; the SDK golden harness checks the declaration against the measured
# spread. Shared so blur, glow and drop-shadow cannot drift apart on the same question.
GAUSSIAN_VISIBLE_SIGMAS = 3.0

__all__ = ["RGBA", "GAUSSIAN_VISIBLE_SIGMAS", "Points", "RGBAColor"]

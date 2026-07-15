"""Shared pydantic field types for effect parameter schemas.

These field helpers are part of the stable extension surface and now live in
:mod:`arcavex.sdk.params`; the built-in effects re-export them from here so their imports and
the SDK stay one definition. See the SDK module for the normalization rules.
"""

from __future__ import annotations

from arcavex.sdk.params import RGBA, Points, RGBAColor

__all__ = ["RGBA", "Points", "RGBAColor"]

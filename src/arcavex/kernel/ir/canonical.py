"""Canonical serialization and hashing.

Canonicalization produces a byte-stable representation independent of authoring order and
formatting so that template versions, run manifests, and cache keys hash identically for
equivalent inputs. Rules (spec §3.1.4): UTF-8 NFC strings, units already normalized to
points by the caller, sorted mapping keys, stable list order, a normalized numeric
representation, and no absolute filesystem paths.

Numeric normalization (CR-13): an authored integer and a computed float of equal value must
hash identically, so ``2`` and ``2.0`` produce the same bytes. Floats are rounded to six
decimal places and an integral result collapses to an ``int``; non-integral floats keep the
rounded float. Numbers stay JSON numbers (not strings), so a numeric ``2`` and the string
``"2"`` remain distinct. Booleans are preserved as JSON booleans, never coerced to numbers.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

# Floats whose magnitude is below this collapse to ``int`` when integral; above it, integer
# round-trip through ``float`` is no longer exact, so the value is kept as a float.
_INT_COLLAPSE_LIMIT = 1e15
_FLOAT_DECIMALS = 6


def _canonical_number(value: int | float) -> int | float:
    """Return the canonical numeric form of ``value`` (CR-13 int/float unification).

    Integers pass through exactly. Floats are rounded to six decimals; an integral result
    within the safe range collapses to ``int`` so ``2.0`` and ``2`` coincide, while a
    non-integral value keeps its rounded float form. ``-0.0`` collapses to ``0``.
    """
    if isinstance(value, int):
        return value
    rounded = round(value, _FLOAT_DECIMALS)
    if rounded == 0.0:
        rounded = 0.0  # collapse -0.0
    if rounded.is_integer() and abs(rounded) < _INT_COLLAPSE_LIMIT:
        return int(rounded)
    return rounded


def canonicalize(value: Any) -> Any:
    """Return a JSON-compatible canonical form of ``value``.

    Mappings become key-sorted dicts, sequences keep their order, strings are NFC
    normalized, and numbers use a normalized representation (see :func:`_canonical_number`).
    Callers are responsible for normalizing units to points and stripping absolute paths
    before canonicalizing.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _canonical_number(value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(k)): canonicalize(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    raise TypeError(f"cannot canonicalize value of type {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Serialize ``value`` to canonical, deterministic UTF-8 JSON bytes."""
    import json

    canonical = canonicalize(value)
    text = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,  # already sorted by canonicalize
    )
    return text.encode("utf-8")


def canonical_hash(value: Any) -> str:
    """Return the SHA-256 hex digest of the canonical form of ``value``."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()

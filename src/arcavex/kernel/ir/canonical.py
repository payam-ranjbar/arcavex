"""Canonical serialization and hashing.

Canonicalization produces a byte-stable representation independent of authoring order and
formatting so that template versions, run manifests, and cache keys hash identically for
equivalent inputs. Rules (spec §3.1.4): UTF-8 NFC strings, units already normalized to
points by the caller, sorted mapping keys, stable list order, normalized float
representation (``repr`` of ``round(x, 6)``), and no absolute filesystem paths.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

from arcavex.kernel.ir.units import _norm_float


def canonicalize(value: Any) -> Any:
    """Return a JSON-compatible canonical form of ``value``.

    Mappings become key-sorted dicts, sequences keep their order, strings are NFC
    normalized, and floats use a normalized representation. Callers are responsible for
    normalizing units to points and stripping absolute paths before canonicalizing.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        return _norm_float(value)
    if isinstance(value, int):
        return value
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
    # TODO(CR-13): before this gains a production caller (Phase 4 provenance), reconcile the
    # int/float canonical text forms — `_norm_float(2.0)` and the int `2` must serialize
    # identically so an authored `2` and a computed `2.0` do not hash differently. Tracked as
    # the CR-13 canonical-float ticket; not required to close Phase 1.
    return hashlib.sha256(canonical_bytes(value)).hexdigest()

"""Canonical serialization and hashing stability tests."""

from __future__ import annotations

import unicodedata

from arcavex.kernel.ir.canonical import canonical_bytes, canonical_hash, canonicalize


def test_key_order_independence() -> None:
    a = {"b": 1, "a": 2, "c": [3, 2, 1]}
    b = {"c": [3, 2, 1], "a": 2, "b": 1}
    assert canonical_hash(a) == canonical_hash(b)


def test_list_order_preserved() -> None:
    assert canonical_hash([1, 2, 3]) != canonical_hash([3, 2, 1])


def test_float_normalization() -> None:
    assert canonical_hash({"x": 1.0000001}) == canonical_hash({"x": 1.0000000})
    assert canonicalize(1.5) == "1.5"
    assert canonicalize(2.0) == "2"


def test_nfc_normalization() -> None:
    decomposed = unicodedata.normalize("NFD", "é")
    composed = unicodedata.normalize("NFC", "é")
    assert decomposed != composed
    assert canonical_hash(decomposed) == canonical_hash(composed)


def test_deterministic_bytes() -> None:
    value = {"seed": 8412, "nodes": [{"id": "a"}, {"id": "b"}]}
    assert canonical_bytes(value) == canonical_bytes(value)


def test_bool_not_int() -> None:
    assert canonicalize(True) is True
    assert canonicalize(1) == 1

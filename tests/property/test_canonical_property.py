"""Property tests for canonical hashing stability (spec §3.1.4, CR-13).

The canonical serializer must be independent of authoring order and numeric spelling: reordering
mapping keys or re-serializing the same value must not change the hash, and an integer and a
float of equal value must hash identically (the CR-13 unification).
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from arcavex.kernel.ir.canonical import canonical_bytes, canonical_hash

# JSON-like values: scalars, lists, and string-keyed maps, bounded in depth.
_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=8),
)
_values = st.recursive(
    _scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=6), children, max_size=5),
    ),
    max_leaves=20,
)


def _shuffle_keys(value: Any) -> Any:
    """Return a structurally equal value with mapping keys reinserted in reverse order."""
    if isinstance(value, dict):
        return {k: _shuffle_keys(value[k]) for k in reversed(list(value))}
    if isinstance(value, list):
        return [_shuffle_keys(v) for v in value]
    return value


@given(_values)
def test_reserialization_is_stable(value: Any) -> None:
    assert canonical_bytes(value) == canonical_bytes(value)


@given(_values)
def test_key_order_independent(value: Any) -> None:
    assert canonical_hash(value) == canonical_hash(_shuffle_keys(value))


@given(st.integers(min_value=-1_000_000, max_value=1_000_000))
def test_int_and_float_of_equal_value_hash_equal(n: int) -> None:
    # CR-13: an authored int and a computed float of the same value are indistinguishable.
    assert canonical_hash(n) == canonical_hash(float(n))
    assert canonical_hash({"x": [n]}) == canonical_hash({"x": [float(n)]})


@given(st.integers(min_value=-1000, max_value=1000))
def test_number_and_its_string_spelling_differ(n: int) -> None:
    # Numbers remain JSON numbers, so a numeric value never collides with its string form.
    assert canonical_hash(n) != canonical_hash(str(n))

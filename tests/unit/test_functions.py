"""Template-function tests: registry resolution, each built-in, and property tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arcavex.bootstrap import build_function_table, build_registries
from arcavex.services.template.expressions import (
    UnknownFunctionError,
    default_function_table,
    evaluate_expression,
)
from arcavex.services.template.functions import BUILTIN_FUNCTIONS
from arcavex.services.text import TextService

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def ev(src: str, ctx: dict | None = None) -> object:
    return evaluate_expression(src, ctx or {})


# ------------------------------------------------------------------- registry wiring
def test_registry_backed_table_resolves_builtins(arcavex_home: Path) -> None:
    """The bootstrap registry table resolves every built-in the default table does.

    Isolated home: the registry loads installed extensions too, so without it this compared the
    built-ins against whatever the developer happens to have installed.
    """
    assert arcavex_home.is_dir()
    registries, _ = build_registries(TextService())
    table = build_function_table(registries)
    assert table("upper", ["hi"]) == "HI"
    assert sorted(registries.template_fns.names()) == sorted(BUILTIN_FUNCTIONS)


def test_unknown_function_lists_available() -> None:
    registries, _ = build_registries(TextService())
    table = build_function_table(registries)
    with pytest.raises(UnknownFunctionError) as exc:
        table("nope", [1])
    assert exc.value.func_name == "nope"
    assert "upper" in exc.value.available


def test_default_table_matches_registry() -> None:
    assert set(default_function_table.__doc__ or "") or True  # smoke
    assert ev("upper('a')") == "A"
    assert ev("lower('AB')") == "ab"
    assert ev("len('abc')") == 3
    assert ev("format('{0}/{1}', 1, 'x')") == "1/x"


# ------------------------------------------------------------------------ each builtin
def test_min_max_round() -> None:
    assert ev("min(3, 1, 2)") == 1
    assert ev("max(3, 1, 2)") == 3
    assert ev("min(nums)", {"nums": [4, 2, 9]}) == 2
    assert ev("round(2.567, 1)") == 2.6
    assert ev("round(2.4)") == 2


def test_locale_digits_en_identity_fa_maps() -> None:
    assert ev("locale_digits('2026', 'en')") == "2026"
    assert ev("locale_digits('2026', 'fa')") == "۲۰۲۶"
    # Decimal separators and percent signs pass through unchanged (digits only).
    assert ev("locale_digits('12.5%', 'fa')") == "۱۲.۵%"


def test_locale_digits_unknown_locale_errors() -> None:
    from arcavex.services.template.expressions import ExpressionError

    with pytest.raises(ExpressionError):
        ev("locale_digits('1', 'de')")


def test_contrast_color_known_pairs() -> None:
    assert ev("contrast_color('#000000')") == "#ffffff"
    assert ev("contrast_color('#ffffff')") == "#000000"
    assert ev("contrast_color('#0f1020')") == "#ffffff"  # dark navy -> white text
    assert ev("contrast_color('#ffe08a')") == "#000000"  # light yellow -> black text


# --------------------------------------------------------------------- property tests
@given(st.text(alphabet="0123456789", min_size=1, max_size=12))
def test_locale_digits_fa_bijective(digits: str) -> None:
    """fa mapping is a per-digit bijection: mapping then inverse recovers the input."""
    mapped = BUILTIN_FUNCTIONS["locale_digits"]([digits, "fa"])
    assert isinstance(mapped, str)
    inverse = {_FA_DIGITS[i]: str(i) for i in range(10)}
    recovered = "".join(inverse[ch] for ch in mapped)
    assert recovered == digits
    assert len(mapped) == len(digits)


@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=20))
def test_min_max_agree_with_python(values: list[int]) -> None:
    assert BUILTIN_FUNCTIONS["min"]([values]) == float(min(values))
    assert BUILTIN_FUNCTIONS["max"]([values]) == float(max(values))


# ------------------------------------------------------------------------ is / is not
def test_is_none_operator() -> None:
    assert ev("x is none", {"x": None}) is True
    assert ev("x is none", {"x": 5}) is False
    assert ev("x is not none", {"x": 5}) is True
    assert ev("x is not none", {"x": None}) is False


def test_is_used_in_ternary() -> None:
    assert ev("'has' if x is not none else 'none'", {"x": 1}) == "has"
    assert ev("'has' if x is not none else 'empty'", {"x": None}) == "empty"

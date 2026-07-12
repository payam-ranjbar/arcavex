"""Expression evaluator tests: values, precedence, budget, missing variables."""

from __future__ import annotations

import pytest

from arcavex.services.template.expressions import (
    BudgetError,
    ExpressionError,
    MissingVariableError,
    evaluate_expression,
    render_value,
)

CTX = {
    "title": "Hello",
    "count": 3,
    "price": 2.5,
    "flag": True,
    "guests": [{"name": "Ann"}, {"name": "Bo"}],
    "event": {"city": "Tehran"},
    "nothing": None,
}


def ev(src: str) -> object:
    return evaluate_expression(src, CTX)


def test_literals() -> None:
    assert ev("42") == 42
    assert ev("3.5") == 3.5
    assert ev("'hi'") == "hi"
    assert ev("true") is True
    assert ev("none") is None


def test_variable_paths() -> None:
    assert ev("title") == "Hello"
    assert ev("event.city") == "Tehran"
    assert ev("guests[0].name") == "Ann"
    assert ev("guests[1].name") == "Bo"


def test_arithmetic_and_precedence() -> None:
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("10 % 3") == 1
    assert ev("count - 1") == 2


def test_comparisons_and_boolean() -> None:
    assert ev("count > 2") is True
    assert ev("count == 3 and flag") is True
    assert ev("count > 5 or flag") is True
    assert ev("not flag") is False


def test_ternary() -> None:
    assert ev("'yes' if flag else 'no'") == "yes"
    assert ev("'big' if count > 10 else 'small'") == "small"


def test_string_concat_and_functions() -> None:
    assert ev("title + '!'") == "Hello!"
    assert ev("upper(title)") == "HELLO"
    assert ev("lower('ABC')") == "abc"
    assert ev("len(guests)") == 2
    assert ev("format('{0}-{1}', count, title)") == "3-Hello"


def test_default_operator() -> None:
    assert ev("missing | default('fallback')") == "fallback"
    assert ev("nothing | default('x')") == "x"
    assert ev("title | default('x')") == "Hello"


def test_missing_variable_raises() -> None:
    with pytest.raises(MissingVariableError) as exc:
        ev("does_not_exist")
    assert exc.value.path == "does_not_exist"


def test_missing_nested_path() -> None:
    with pytest.raises(MissingVariableError):
        ev("event.missing")


def test_syntax_error() -> None:
    with pytest.raises(ExpressionError):
        ev("1 +")


def test_division_by_zero() -> None:
    with pytest.raises(ExpressionError):
        ev("1 / 0")


def test_budget_enforced() -> None:
    # A pathologically large expression is rejected deterministically by the token cap
    # rather than running unbounded or blowing the Python stack.
    expr = "1" + " + 1" * 5000
    with pytest.raises(BudgetError):
        ev(expr)


def test_render_value_exact_keeps_type() -> None:
    assert render_value("{{ count }}", CTX) == 3
    assert render_value("{{ flag }}", CTX) is True


def test_render_value_interpolation_stringifies() -> None:
    assert render_value("Count: {{ count }} items", CTX) == "Count: 3 items"
    assert render_value("{{ title }} / {{ event.city }}", CTX) == "Hello / Tehran"


def test_render_value_escape() -> None:
    assert render_value("\\{{ literal }}", CTX) == "{{ literal }}"


def test_render_value_plain_passthrough() -> None:
    assert render_value("no expressions here", CTX) == "no expressions here"

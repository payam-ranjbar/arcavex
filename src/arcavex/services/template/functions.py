"""Canonical implementations of the built-in template functions.

These pure, deterministic callables are the single source of truth for the functions callable
from ``{{ … }}`` expressions (spec §3.2 ``TemplateFunction``, §4.4). The built-in
:class:`~arcavex.kernel.contracts.spi.TemplateFunction` components in
``arcavex.builtin.template_fns`` wrap these implementations so the registry and the evaluator
never carry two parallel function tables (Phase 0 CR-15). Each takes the already-evaluated
positional arguments as a list and returns a :data:`Value`; misuse raises :class:`ValueError`,
which the evaluator surfaces as a located ``ARC-TPL`` diagnostic.

The evaluator (a service) resolves functions through an injected table, so ``services`` never
imports ``builtin``; ``bootstrap`` wires the registry-backed table for production use.
"""

from __future__ import annotations

from collections.abc import Callable

from arcavex.kernel.contracts.types import Value
from arcavex.kernel.ir.colors import Color

# Persian (Extended Arabic-Indic) digits U+06F0..U+06F9, indexed by their ASCII digit value.
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_SUPPORTED_LOCALES = ("en", "fa")


def _stringify_scalar(value: Value) -> str:
    """Render a scalar to text the way interpolation does (no list/object)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    raise ValueError("expected a string or number")


def _one(name: str, args: list[Value]) -> Value:
    if len(args) != 1:
        raise ValueError(f"{name}() takes exactly one argument")
    return args[0]


def _upper(args: list[Value]) -> Value:
    value = _one("upper", args)
    if not isinstance(value, str):
        raise ValueError("upper() requires a string")
    return value.upper()


def _lower(args: list[Value]) -> Value:
    value = _one("lower", args)
    if not isinstance(value, str):
        raise ValueError("lower() requires a string")
    return value.lower()


def _len(args: list[Value]) -> Value:
    value = _one("len", args)
    if isinstance(value, (str, list, dict)):
        return len(value)
    raise ValueError("len() requires a string, list, or object")


def _format(args: list[Value]) -> Value:
    if not args or not isinstance(args[0], str):
        raise ValueError("format() requires a template string as its first argument")
    template, rest = args[0], args[1:]
    try:
        return template.format(*[_stringify_scalar(a) for a in rest])
    except (IndexError, KeyError, ValueError) as exc:
        raise ValueError(f"format() failed: {exc}") from exc


def _numbers(name: str, args: list[Value]) -> list[float]:
    # ``min([a, b])`` and ``min(a, b, …)`` both work; a lone list argument is spread.
    values: list[Value]
    if len(args) == 1 and isinstance(args[0], list):
        values = args[0]
    else:
        values = args
    if not values:
        raise ValueError(f"{name}() requires at least one number")
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}() requires numbers")
        out.append(float(value))
    return out


def _min(args: list[Value]) -> Value:
    return min(_numbers("min", args))


def _max(args: list[Value]) -> Value:
    return max(_numbers("max", args))


def _round(args: list[Value]) -> Value:
    if not 1 <= len(args) <= 2:
        raise ValueError("round() takes a number and an optional digit count")
    value = args[0]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("round() requires a number")
    if len(args) == 2:
        ndigits = args[1]
        if isinstance(ndigits, bool) or not isinstance(ndigits, int):
            raise ValueError("round() digit count must be an integer")
        return round(float(value), ndigits)
    return round(float(value))


def _locale_digits(args: list[Value]) -> Value:
    if len(args) != 2:
        raise ValueError("locale_digits() takes a text value and a locale")
    text = _stringify_scalar(args[0])
    locale = args[1]
    if not isinstance(locale, str):
        raise ValueError("locale_digits() locale must be a string")
    if locale not in _SUPPORTED_LOCALES:
        available = ", ".join(_SUPPORTED_LOCALES)
        raise ValueError(f"locale_digits() unknown locale {locale!r} (supported: {available})")
    if locale == "en":
        return text
    # 'fa': map ASCII digits to Persian digits; decimal separators and percent signs pass
    # through unchanged so "12.5%" -> "۱۲.۵%". Only digit code points are substituted.
    return text.translate({ord("0") + i: _FA_DIGITS[i] for i in range(10)})


def _contrast_color(args: list[Value]) -> Value:
    value = _one("contrast_color", args)
    if not isinstance(value, str):
        raise ValueError("contrast_color() requires a color string")
    try:
        color = Color.parse(value)
    except ValueError as exc:
        raise ValueError(f"contrast_color() got an invalid color: {value!r}") from exc
    luminance = _relative_luminance(color.r, color.g, color.b)
    # WCAG-style pivot (~0.179): dark backgrounds get white text, light get black.
    return "#000000" if luminance > 0.179 else "#ffffff"


def _relative_luminance(r: float, g: float, b: float) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


# The canonical registry of built-in template functions, keyed by call name. Both the
# expression evaluator's default table and the ``builtin/template_fns`` contract wrappers
# resolve against this one mapping.
BUILTIN_FUNCTIONS: dict[str, Callable[[list[Value]], Value]] = {
    "upper": _upper,
    "lower": _lower,
    "len": _len,
    "format": _format,
    "min": _min,
    "max": _max,
    "round": _round,
    "locale_digits": _locale_digits,
    "contrast_color": _contrast_color,
}

# Human/AI-facing signature and one-line doc per built-in, surfaced by ``template inspect``
# (DX-3) so a consumer need not read source to call a function. Keyed by the same call name.
FUNCTION_SIGNATURES: dict[str, tuple[str, str]] = {
    "upper": ("upper(text: string) -> string", "Uppercase a string."),
    "lower": ("lower(text: string) -> string", "Lowercase a string."),
    "len": ("len(value: string|list|object) -> number", "Length of a string, list, or object."),
    "format": (
        "format(fmt: string, *args) -> string",
        "printf-style substitution of positional '{}' fields.",
    ),
    "min": ("min(*numbers | list) -> number", "Minimum of numbers or a single list of numbers."),
    "max": ("max(*numbers | list) -> number", "Maximum of numbers or a single list of numbers."),
    "round": (
        "round(value: number, ndigits: number = 0) -> number",
        "Round a number to an optional digit count (banker's rounding).",
    ),
    "locale_digits": (
        "locale_digits(text, locale: 'en'|'fa') -> string",
        "Map ASCII digits in text to a locale's digit set (fa -> ۰۱۲۳۴۵۶۷۸۹).",
    ),
    "contrast_color": (
        "contrast_color(color: string) -> string",
        "Return '#000000' or '#ffffff' for best WCAG contrast on the given color.",
    ),
}

__all__ = ["BUILTIN_FUNCTIONS", "FUNCTION_SIGNATURES"]

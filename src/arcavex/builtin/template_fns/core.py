"""Built-in template functions as :class:`TemplateFunction` contract components.

Each class is a thin wrapper over the canonical pure implementation in
``arcavex.services.template.functions`` so the registry and the expression evaluator resolve
against exactly one function table (no parallel implementations — Phase 0 CR-15). Registering
them here (via :mod:`arcavex.bootstrap`) is what lets production expression evaluation route
through the ``TemplateFunction`` registry as the spec (§3.2, §4.4) requires.
"""

from __future__ import annotations

from typing import ClassVar

from arcavex.kernel.contracts.spi import TemplateFunction
from arcavex.kernel.contracts.types import Value
from arcavex.services.template.functions import BUILTIN_FUNCTIONS


class _WrappedFn(TemplateFunction):
    """Base wrapper delegating to a canonical implementation keyed by ``name``."""

    def call(self, *args: Value) -> Value:
        """Evaluate the function against the canonical implementation."""
        return BUILTIN_FUNCTIONS[self.name](list(args))


class UpperFn(_WrappedFn):
    """Uppercase a string."""

    name: ClassVar[str] = "upper"


class LowerFn(_WrappedFn):
    """Lowercase a string."""

    name: ClassVar[str] = "lower"


class LenFn(_WrappedFn):
    """Length of a string, list, or object."""

    name: ClassVar[str] = "len"


class FormatFn(_WrappedFn):
    """Format a template string with positional ``{}`` fields."""

    name: ClassVar[str] = "format"


class MinFn(_WrappedFn):
    """Minimum of numbers (or a single list of numbers)."""

    name: ClassVar[str] = "min"


class MaxFn(_WrappedFn):
    """Maximum of numbers (or a single list of numbers)."""

    name: ClassVar[str] = "max"


class RoundFn(_WrappedFn):
    """Round a number to an optional digit count."""

    name: ClassVar[str] = "round"


class LocaleDigitsFn(_WrappedFn):
    """Map ASCII digits in text to a locale's digit set (``fa`` -> ۰۱۲۳۴۵۶۷۸۹)."""

    name: ClassVar[str] = "locale_digits"


class ContrastColorFn(_WrappedFn):
    """Return ``#000000`` or ``#ffffff`` for best contrast on the given color."""

    name: ClassVar[str] = "contrast_color"


def builtin_template_functions() -> list[TemplateFunction]:
    """Return the list of built-in template functions to register."""
    return [
        UpperFn(),
        LowerFn(),
        LenFn(),
        FormatFn(),
        MinFn(),
        MaxFn(),
        RoundFn(),
        LocaleDigitsFn(),
        ContrastColorFn(),
    ]

"""Core deterministic template functions.

Each is a pure function with no I/O or side effects, implementing the
:class:`TemplateFunction` contract. The Phase 0 expression evaluator also recognises these
names inline; registering them here establishes the contract and registry surface that later
phases route through.
"""

from __future__ import annotations

from typing import ClassVar

from arcavex.kernel.contracts.spi import TemplateFunction
from arcavex.kernel.contracts.types import Value


class UpperFn(TemplateFunction):
    """Uppercase a string."""

    name: ClassVar[str] = "upper"

    def call(self, *args: Value) -> Value:
        """Return ``args[0]`` uppercased."""
        if len(args) != 1 or not isinstance(args[0], str):
            raise ValueError("upper() requires exactly one string argument")
        return args[0].upper()


class LowerFn(TemplateFunction):
    """Lowercase a string."""

    name: ClassVar[str] = "lower"

    def call(self, *args: Value) -> Value:
        """Return ``args[0]`` lowercased."""
        if len(args) != 1 or not isinstance(args[0], str):
            raise ValueError("lower() requires exactly one string argument")
        return args[0].lower()


class LenFn(TemplateFunction):
    """Length of a string, list, or object."""

    name: ClassVar[str] = "len"

    def call(self, *args: Value) -> Value:
        """Return the length of ``args[0]``."""
        if len(args) != 1 or not isinstance(args[0], (str, list, dict)):
            raise ValueError("len() requires a string, list, or object")
        return len(args[0])


def builtin_template_functions() -> list[TemplateFunction]:
    """Return the list of built-in template functions to register."""
    return [UpperFn(), LowerFn(), LenFn()]

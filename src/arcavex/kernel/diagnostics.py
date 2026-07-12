"""The single structured error model that crosses every boundary.

Located, hinted diagnostics are simultaneously the human authoring experience and the AI
self-correction loop (spec §3.6). Every diagnostic carries a stable code, a severity, a
message, an optional source location, and a hint. No raw exception ever crosses the API
facade; unexpected exceptions are wrapped as ``ARC-INT-999``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["error", "warning", "info"]

# Code namespaces per spec §3.6.
NAMESPACES: tuple[str, ...] = (
    "ARC-TPL",  # template / compile
    "ARC-IR",  # schema / semantic
    "ARC-LAY",  # layout
    "ARC-FX",  # effects
    "ARC-RND",  # render
    "ARC-EXP",  # export
    "ARC-AST",  # assets
    "ARC-EXT",  # extensions
    "ARC-PRJ",  # projects
    "ARC-INT",  # internal
)


class SourceLocation(BaseModel):
    """A location in an authored source file."""

    model_config = ConfigDict(frozen=True)

    file: str | None = None
    keypath: str | None = None
    line: int | None = None
    column: int | None = None


class Diagnostic(BaseModel):
    """A single structured diagnostic."""

    model_config = ConfigDict(frozen=True)

    code: str
    severity: Severity = "error"
    message: str
    source: SourceLocation | None = None
    hint: str | None = None

    def is_error(self) -> bool:
        """Whether this diagnostic is an error."""
        return self.severity == "error"


def diagnostic(
    code: str,
    message: str,
    *,
    severity: Severity = "error",
    file: str | None = None,
    keypath: str | None = None,
    line: int | None = None,
    column: int | None = None,
    hint: str | None = None,
) -> Diagnostic:
    """Construct a :class:`Diagnostic`, validating the code namespace.

    Args:
        code: A stable diagnostic code such as ``ARC-TPL-014``.
        message: A human-readable description of the problem.
        severity: One of ``error``, ``warning``, ``info``.
        file: Source file path, if known.
        keypath: Structured key path into the source, if known.
        line: 1-based line number, if known.
        column: 1-based column number, if known.
        hint: An actionable correction hint.

    Returns:
        The constructed diagnostic.
    """
    namespace = code.rsplit("-", 1)[0]
    if namespace not in NAMESPACES:
        raise ValueError(f"unknown diagnostic namespace in code {code!r}")
    source: SourceLocation | None = None
    if file is not None or keypath is not None or line is not None or column is not None:
        source = SourceLocation(file=file, keypath=keypath, line=line, column=column)
    return Diagnostic(
        code=code, severity=severity, message=message, source=source, hint=hint
    )


class DiagnosticError(Exception):
    """An exception carrying one or more diagnostics.

    Raised inside the engine to unwind to the nearest handler, which accumulates the
    diagnostics into a result. It must never escape the API facade.
    """

    def __init__(self, diagnostics: list[Diagnostic] | Diagnostic) -> None:
        if isinstance(diagnostics, Diagnostic):
            diagnostics = [diagnostics]
        self.diagnostics: list[Diagnostic] = diagnostics
        super().__init__("; ".join(f"{d.code}: {d.message}" for d in diagnostics))


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    """Whether any diagnostic in the list is an error."""
    return any(d.is_error() for d in diagnostics)


# Diagnostic codes that clients map to specific exit codes (§6.1.3). Kept here so the
# producing site and the CLI's exit-code table cannot drift apart.
BUDGET_CODE = "ARC-TPL-062"  # expression exceeded its evaluation budget -> exit 4
MISSING_FONT_CODE = "ARC-RND-010"  # requested font family not in the bundled DB -> exit 3


def internal_error(message: str, *, detail: str | None = None) -> Diagnostic:
    """Build the ``ARC-INT-999`` diagnostic for an unexpected failure."""
    return Diagnostic(
        code="ARC-INT-999",
        severity="error",
        message=message,
        hint=(
            "This is an internal engine error. "
            + (f"Detail: {detail}" if detail else "Please report it with the input.")
        ),
    )

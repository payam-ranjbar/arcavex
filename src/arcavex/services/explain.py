"""Diagnostic-code explanation lookup for ``arcavex explain`` (spec §3.7 / §6.1.3).

Resolves a diagnostic code against the canonical
:mod:`arcavex.services.diagnostics_catalog` and returns a kernel :class:`DiagnosticHelp`.
Unknown codes return ``found=False`` with an actionable message rather than raising.
"""

from __future__ import annotations

from arcavex.kernel.api import DiagnosticHelp
from arcavex.kernel.diagnostics import NAMESPACES
from arcavex.services.diagnostics_catalog import CATALOG


def explain_code(code: str) -> DiagnosticHelp:
    """Return help for ``code`` (already normalized to uppercase by the caller)."""
    entry = CATALOG.get(code)
    if entry is not None:
        return DiagnosticHelp(
            code=code,
            found=True,
            title=entry.title,
            summary=entry.summary,
            fix=entry.fix,
        )
    namespace = code.rsplit("-", 1)[0] if "-" in code else code
    if namespace not in NAMESPACES:
        message = (
            f"Unknown diagnostic code {code!r}. Codes look like 'ARC-TPL-014'; "
            f"valid namespaces are: {', '.join(NAMESPACES)}."
        )
    else:
        message = (
            f"No documentation entry for {code!r}. It may not be emitted by this build."
        )
    return DiagnosticHelp(code=code, found=False, message=message)

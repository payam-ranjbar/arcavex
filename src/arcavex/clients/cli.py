"""Arcavex command-line interface (Typer).

Direct file mode for Phase 0: ``render`` and ``validate``. The CLI only parses arguments,
calls the service facade, and formats results (human via Rich, or ``--json``). Exit codes
follow spec §6.1.3: 0 success/warnings, 1 validation error, 2 usage, 3 missing
dependency/font/asset/template, 4 budget, 5 internal (``ARC-INT-999``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import Facade
from arcavex.kernel.diagnostics import (
    BUDGET_CODE,
    MISSING_FONT_CODE,
    Diagnostic,
    diagnostic,
    has_errors,
)

app = typer.Typer(add_completion=False, help="Arcavex rendering engine (Phase 0 slice).")

# Every machine-readable response carries this so consumers key on a version, not shape.
RESPONSE_VERSION = 1

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_USAGE = 2
EXIT_MISSING = 3
EXIT_BUDGET = 4
EXIT_INTERNAL = 5

# Codes that map to exit 3 (missing template/asset/font). ARC-TPL-001 = file not found;
# ARC-AST-* = missing/undecodable asset; MISSING_FONT_CODE = font not in bundled DB.
_MISSING_CODES = {"ARC-TPL-001", MISSING_FONT_CODE}
_MISSING_PREFIXES = ("ARC-AST",)
_BUDGET_CODES = {BUDGET_CODE}


def _exit_code_for(diagnostics: list[Diagnostic], ok: bool) -> int:
    errors = [d for d in diagnostics if d.is_error()]
    if not errors:
        return EXIT_OK if ok else EXIT_VALIDATION
    codes = [d.code for d in errors]
    if any(c.startswith("ARC-INT") for c in codes):
        return EXIT_INTERNAL
    if any(c in _BUDGET_CODES for c in codes):
        return EXIT_BUDGET
    if any(c in _MISSING_CODES or c.startswith(_MISSING_PREFIXES) for c in codes):
        return EXIT_MISSING
    return EXIT_VALIDATION


def _force_utf8_stdout() -> None:
    """Make ``--json`` output codepage-independent on Windows consoles."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")


def _build_facade_or_exit(console: Console, quiet: bool) -> Facade:
    """Build the facade, converting init failures into a diagnostic instead of a traceback."""
    try:
        return build_facade()
    except Exception as exc:  # noqa: BLE001 - CLI boundary must not leak a traceback
        diag = diagnostic(
            "ARC-INT-999",
            "Engine initialization failed",
            hint=(
                "The rendering engine could not start. Ensure 'icudtl.dat' sits beside the "
                "Python interpreter and fonts are installed under library-seed/fonts. "
                f"Detail: {exc!r}"
            ),
        )
        _print_diagnostics(console, [diag], quiet)
        raise typer.Exit(EXIT_INTERNAL) from exc


def _report_inferences(console: Console, inferred: dict[str, str], quiet: bool) -> None:
    if quiet or not inferred:
        return
    parts = ", ".join(f"{k}={v}" for k, v in inferred.items())
    console.print(f"[dim]inferred:[/dim] {parts}")


def _diag_to_dict(diag: Diagnostic) -> dict[str, object]:
    return diag.model_dump(mode="json", exclude_none=True)


def _print_diagnostics(console: Console, diagnostics: list[Diagnostic], quiet: bool) -> None:
    if quiet:
        return
    for diag in diagnostics:
        color = {"error": "red", "warning": "yellow", "info": "cyan"}.get(diag.severity, "white")
        location = ""
        if diag.source is not None:
            parts = []
            if diag.source.file:
                parts.append(diag.source.file)
            if diag.source.line is not None:
                parts.append(f"line {diag.source.line}")
            if diag.source.keypath:
                parts.append(f"at {diag.source.keypath}")
            if parts:
                location = " (" + ", ".join(parts) + ")"
        console.print(
            f"[{color}]{diag.severity.upper()} {diag.code}[/{color}] {diag.message}{location}"
        )
        if diag.hint:
            console.print(f"  [dim]hint:[/dim] {diag.hint}")


@app.command()
def render(
    template: Path = typer.Argument(..., help="Path to the template YAML file."),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output PNG path. Defaults to '<template-stem>.<format>.png' in the CWD.",
    ),
    dpi: int | None = typer.Option(None, "--dpi", help="Override render DPI."),
    debug: bool = typer.Option(False, "--debug", help="Enable debug overlays (reserved)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human diagnostics."),
) -> None:
    """Render a template with data to a PNG file."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.render_file(
        template=template,
        data=data,
        format_name=format_name,
        output=output,
        dpi=dpi,
        debug=debug,
    )
    if json_out:
        typer.echo(
            json.dumps(
                {
                    "response_version": RESPONSE_VERSION,
                    "ok": result.ok,
                    "output_path": result.output_path,
                    "content_sha256": result.content_sha256,
                    "inferred": result.inferred,
                    "diagnostics": [_diag_to_dict(d) for d in result.diagnostics],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _report_inferences(console, result.inferred, quiet)
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(f"[green]Rendered[/green] {result.output_path}")
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


@app.command()
def validate(
    template: Path = typer.Argument(..., help="Path to the template YAML file."),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human diagnostics."),
) -> None:
    """Validate a template (and optional data) without rendering."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    diagnostics = facade.validate_template(
        template=template, data=data, format_name=format_name
    )
    ok = not has_errors(diagnostics)
    if json_out:
        typer.echo(
            json.dumps(
                {
                    "response_version": RESPONSE_VERSION,
                    "ok": ok,
                    "diagnostics": [_diag_to_dict(d) for d in diagnostics],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_diagnostics(console, diagnostics, quiet)
        if ok and not quiet:
            console.print("[green]OK[/green] template is valid")
    raise typer.Exit(_exit_code_for(diagnostics, ok))


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()

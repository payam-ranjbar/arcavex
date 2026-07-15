"""Arcavex command-line interface (Typer).

Direct file mode for Phase 0: ``render`` and ``validate``. The CLI only parses arguments,
calls the service facade, and formats results (human via Rich, or ``--json``). Exit codes
follow spec §6.1.3: 0 success/warnings, 1 validation error, 2 usage, 3 missing
dependency/font/asset/template, 4 budget, 5 internal (``ARC-INT-999``).
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape as _rich_escape
from rich.table import Table

from arcavex.bootstrap import build_facade
from arcavex.clients.watch import run_watch
from arcavex.kernel.api import (
    RESPONSE_VERSION,
    DoctorReport,
    Facade,
    LayoutReport,
    PreviewResult,
)
from arcavex.kernel.diagnostics import (
    BUDGET_CODE,
    MISSING_FONT_CODE,
    Diagnostic,
    diagnostic,
    has_errors,
)


def _esc(value: object) -> str:
    """Escape Rich markup so literal '[...]' text (e.g. '[repeat]') displays (RR1-2)."""
    return _rich_escape(str(value))


app = typer.Typer(add_completion=False, help="Arcavex rendering engine.")
template_app = typer.Typer(add_completion=False, help="Template authoring commands.")
app.add_typer(template_app, name="template")
layout_app = typer.Typer(add_completion=False, help="Layout inspection commands.")
app.add_typer(layout_app, name="layout")
style_app = typer.Typer(add_completion=False, help="Style-pack commands.")
app.add_typer(style_app, name="style")


def _engine_version() -> str:
    import importlib.metadata

    try:
        return importlib.metadata.version("arcavex")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev tree without wheel
        return "0+unknown"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"arcavex {_engine_version()}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show the engine version and exit.",
    ),
) -> None:
    """Arcavex rendering engine."""

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
# Both expression budget and the repeat iteration cap are resource limits (exit 4).
_BUDGET_CODES = {BUDGET_CODE, "ARC-TPL-063"}


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
    """Make JSON and human output codepage-independent on Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
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


def _emit_json(payload: object) -> None:
    """Print a pydantic model or plain object as UTF-8 JSON (non-ASCII preserved)."""
    from pydantic import BaseModel

    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


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
            f"[{color}]{diag.severity.upper()} {diag.code}[/{color}] "
            f"{_esc(diag.message)}{_esc(location)}"
        )
        if diag.hint:
            console.print(f"  [dim]hint:[/dim] {_esc(diag.hint)}")


@app.command()
def render(
    template: Path = typer.Argument(..., help="Path to the template YAML file."),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    locale: str | None = typer.Option(
        None, "--locale", "-l", help="Locale name (application is Phase 2)."
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output PNG path. Defaults to '<template-stem>.<format>.png' in the CWD.",
    ),
    dpi: int | None = typer.Option(None, "--dpi", help="Override render DPI."),
    debug: bool = typer.Option(
        False, "--debug", help="Overlay node bounds, ids, baselines, and the safe-area margin."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human diagnostics."),
) -> None:
    """Render a template with data to a PNG file."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    # RR1-3: announce the render-affecting inferences (output name, sole format) *before* the
    # pipeline runs, so a long A4 render shows the resolved output up front, not only after.
    plan = facade.render_plan(template, data, format_name, output, locale)
    if not json_out:
        _report_inferences(console, plan, quiet)
    result = facade.render_file(
        template=template,
        data=data,
        format_name=format_name,
        locale=locale,
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
        # Any remaining inferences (data source, locale overlay) that were not knowable before
        # the pipeline are reported now, without repeating what the plan already showed.
        remaining = {k: v for k, v in result.inferred.items() if k not in plan}
        _report_inferences(console, remaining, quiet)
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(f"[green]Rendered[/green] {result.output_path}")
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


@app.command()
def validate(
    template: Path = typer.Argument(..., help="Path to the template YAML file."),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    locale: str | None = typer.Option(
        None, "--locale", "-l", help="Locale name (application is Phase 2)."
    ),
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
        template=template, data=data, format_name=format_name, locale=locale
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


@app.command()
def doctor(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress the human table."),
) -> None:
    """Check the environment (Python, Skia, ICU, fonts, temp dir) and engine version."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report = facade.doctor()
    if json_out:
        _emit_json(report)
    elif not quiet:
        _print_doctor_table(console, report)
    raise typer.Exit(EXIT_OK if report.ok else EXIT_MISSING)


def _print_doctor_table(console: Console, report: DoctorReport) -> None:
    console.print(f"[bold]Arcavex[/bold] engine {report.engine_version}")
    table = Table(show_header=True, header_style="bold")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")
    marks = {"ok": "[green]ok[/green]", "warn": "[yellow]warn[/yellow]", "fail": "[red]fail[/red]"}
    for check in report.checks:
        table.add_row(check.name, marks.get(check.status, check.status), check.detail)
    console.print(table)
    for check in report.checks:
        if check.status != "ok" and check.hint:
            console.print(f"  [dim]hint ({check.name}):[/dim] {check.hint}")


@app.command()
def explain(
    code: str = typer.Argument(..., help="A diagnostic code such as ARC-TPL-014."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Explain a diagnostic code: what it means and the typical fix."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    help_ = facade.explain_diagnostic(code)
    if json_out:
        _emit_json(help_)
    elif not quiet:
        if help_.found:
            console.print(f"[bold]{help_.code}[/bold] — {help_.title}")
            console.print(help_.summary or "")
            if help_.fix:
                console.print(f"[dim]fix:[/dim] {help_.fix}")
        else:
            console.print(f"[red]{help_.code}[/red] {help_.message or 'not found'}")
    raise typer.Exit(EXIT_OK if help_.found else EXIT_VALIDATION)


@app.command()
def preview(
    template: Path = typer.Argument(..., help="Template file or directory."),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    locale: str | None = typer.Option(None, "--locale", "-l", help="Locale name."),
    watch: bool = typer.Option(False, "--watch", help="Re-render on every dependent-file save."),
    dpi: int | None = typer.Option(None, "--dpi", help="Override render DPI."),
    debug: bool = typer.Option(False, "--debug", help="Overlay node bounds, ids, and baselines."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human diagnostics."),
) -> None:
    """Render to a stable preview path; with --watch, keep re-rendering on saves."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    if watch:
        _run_preview_watch(
            facade, console, template, data, format_name, locale, dpi, quiet, debug
        )
        raise typer.Exit(EXIT_OK)  # Ctrl+C / stop exits cleanly
    result = facade.render_preview(
        template, data, format_name, locale=locale, dpi=dpi, debug=debug
    )
    if json_out:
        _emit_json(result)
    else:
        _print_preview_line(console, result, quiet, watching=False)
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


def _run_preview_watch(
    facade: Facade,
    console: Console,
    template: Path,
    data: Path | None,
    format_name: str | None,
    locale: str | None,
    dpi: int | None,
    quiet: bool,
    debug: bool = False,
) -> None:
    if not quiet:
        console.print("[dim]watching for changes… (Ctrl+C to stop)[/dim]")
    stop_event = threading.Event()
    seen_ok = {"value": False}

    def on_result(res: PreviewResult) -> None:
        _print_preview_line(console, res, quiet, watching=True, had_good=seen_ok["value"])
        if res.ok:
            seen_ok["value"] = True

    try:
        run_watch(
            facade, template, data, format_name, dpi, on_result,
            locale=locale, debug=debug, stop_event=stop_event,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        stop_event.set()


def _print_preview_line(
    console: Console,
    res: PreviewResult,
    quiet: bool,
    *,
    watching: bool,
    had_good: bool = False,
) -> None:
    if quiet:
        return
    if res.ok:
        # In one-shot mode there is no change to report, so drop the watch-only 'changed='.
        prefix = f"changed={res.changed_file} " if (watching and res.changed_file) else ""
        console.print(
            f"{prefix}compile={res.compile_ms:.1f}ms "
            f"render={res.render_ms:.1f}ms -> {res.output_path}"
        )
    else:
        # A prior good preview is only "kept" if one was ever written (DX-10).
        kept = " (kept last good preview)" if (watching and had_good) else ""
        prefix = f"changed={res.changed_file} " if (watching and res.changed_file) else ""
        console.print(f"[red]{prefix}render failed{kept}[/red]")
        errors = [d for d in res.diagnostics if d.is_error()]
        _print_diagnostics(console, errors[:1] or res.diagnostics[:1], quiet)


@template_app.command("new")
def template_new(
    target: Path = typer.Argument(..., help="Directory to scaffold the template into."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Scaffold a minimal renderable template directory."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.scaffold_template(target.name, target)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(
                f"[green]Created[/green] {result.path} "
                f"(render with --format {result.format})"
            )
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


@template_app.command("check")
def template_check(
    template: Path = typer.Argument(..., help="Template file or directory."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    locale: str | None = typer.Option(
        None, "--locale", "-l", help="Locale name (application is Phase 2)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Validate a template without data (schema + structure + preview_data)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.check_template(template, format_name, locale)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print("[green]OK[/green] template is valid")
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


@template_app.command("inspect")
def template_inspect(
    template: Path = typer.Argument(..., help="Template file or directory."),
    resolved: bool = typer.Option(
        False, "--resolved",
        help="Report final layered values and their originating layer (format/locale patches).",
    ),
    format_name: str | None = typer.Option(
        None, "--format", "-f", help="Format name (with --resolved)."
    ),
    locale: str | None = typer.Option(
        None, "--locale", "-l", help="Locale name (with --resolved)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Report a template's variables, formats, node IDs, functions, and example data."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    if resolved:
        _template_inspect_resolved(
            console, facade, template, format_name, locale, json_out, quiet
        )
        return
    report = facade.inspect_template(template)
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok:
            # CR-6: a template that fails to compile shows its diagnostics in human mode too,
            # not just in the JSON payload, and the exit code reflects the failure.
            _print_diagnostics(console, report.diagnostics, quiet)
        else:
            console.print(f"[bold]variables[/bold] ({len(report.variables)}):")
            for var in report.variables:
                req = "required" if var.required else "optional"
                console.print(f"  {var.name}: {var.type or '?'} ({req}) {var.doc or ''}")
            console.print(f"[bold]formats[/bold]: {', '.join(f.name for f in report.formats)}")
            console.print("[bold]nodes[/bold]:")
            for node in report.nodes:
                tag = "" if node.origin == "static" else f" \\[{node.origin}]"
                console.print(f"  {_esc(node.id)}: {_esc(node.type)}{tag}")
            console.print("[bold]functions[/bold]:")
            for fn in report.functions:
                console.print(f"  {fn.signature}")
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


def _template_inspect_resolved(
    console: Console,
    facade: Facade,
    template: Path,
    format_name: str | None,
    locale: str | None,
    json_out: bool,
    quiet: bool,
) -> None:
    """Render ``template inspect --resolved``: final values and their originating layer (CR-1)."""
    report = facade.inspect_resolved(template, None, format_name, locale)
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok:
            _print_diagnostics(console, report.diagnostics, quiet)
        else:
            console.print(
                f"[bold]resolved[/bold] format={report.format} locale={report.locale or '-'} "
                f"direction={report.direction} digits={report.digits or '-'} "
                f"style={report.style or '-'}"
            )
            if not report.patches:
                console.print("  [dim]no format/locale patches applied[/dim]")
            for p in report.patches:
                mark = "" if p.effective else " [dim](overridden)[/dim]"
                value = "" if p.value is None else f" = {_esc(p.value)}"
                console.print(
                    f"  [cyan]{_esc(p.path)}[/cyan]{value} "
                    f"[dim]<- {_esc(p.layer)} ({p.op})[/dim]{mark}"
                )
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


@template_app.command("split")
def template_split(
    template: Path = typer.Argument(..., help="One-file template to split."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Convert a one-file template into a split directory losslessly."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.split_template(template)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(
                f"[green]Split[/green] {result.directory} into {', '.join(result.files)}"
            )
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


@layout_app.command("inspect")
def layout_inspect(
    template: Path = typer.Argument(..., help="Template file or directory."),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    locale: str | None = typer.Option(None, "--locale", "-l", help="Locale name."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Report resolved geometry: per-node bounds, anchors, overflow, and sibling overlaps."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report = facade.inspect_layout(template, data, format_name, locale)
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok:
            _print_diagnostics(console, report.diagnostics, quiet)
        else:
            _print_layout_report(console, report)
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


def _print_layout_report(console: Console, report: LayoutReport) -> None:
    _report_inferences(console, report.inferred, quiet=False)
    console.print(
        f"[bold]canvas[/bold] {report.canvas_pt[0]:g}x{report.canvas_pt[1]:g}pt "
        f"({report.canvas_px[0]}x{report.canvas_px[1]}px @ {report.dpi}dpi) "
        f"format={report.format} locale={report.locale or '-'}"
    )
    if report.root is not None:
        _print_layout_node(console, report.root, 0)
    if report.overlaps:
        console.print("[bold]overlaps[/bold]:")
        for ov in report.overlaps:
            r = ov.rect_pt
            console.print(
                f"  {_esc(ov.a)} ∩ {_esc(ov.b)} at "
                f"({r[0]:.1f}, {r[1]:.1f}, {r[2]:.1f}, {r[3]:.1f})pt"
            )
    console.print(f"[bold]coverage[/bold]: {report.covered_fraction:.0%} of canvas")
    if report.free_regions:
        console.print("[bold]free regions[/bold] (empty horizontal bands):")
        for r in report.free_regions:
            console.print(
                f"  ({r[0]:.1f}, {r[1]:.1f}, {r[2]:.1f}, {r[3]:.1f})pt"
            )
    for warn in report.warnings:
        console.print(f"[yellow]WARN {warn.code}[/yellow] {_esc(warn.message)}")


def _print_layout_node(console: Console, node: object, depth: int) -> None:
    n = node  # LayoutNodeReport
    pad = "  " * depth
    x, y, w, h = n.bounds_pt  # type: ignore[attr-defined]
    console.print(
        f"{pad}[cyan]{_esc(n.id)}[/cyan] [dim]{n.kind}[/dim] "  # type: ignore[attr-defined]
        f"({x:.1f}, {y:.1f}, {w:.1f}, {h:.1f})pt"
    )
    for anchor in n.anchors:  # type: ignore[attr-defined]
        console.print(
            f"{pad}  [dim]{anchor.axis[0]}:[/dim] {anchor.edge} = "
            f"{_esc(anchor.expression)} → {anchor.resolved_pt:.1f}pt"
        )
    if n.overflow is not None and n.overflow.kind != "none":  # type: ignore[attr-defined]
        o = n.overflow  # type: ignore[attr-defined]
        console.print(
            f"{pad}  [yellow]overflow[/yellow]: {o.kind} "
            f"(measured {o.measured_w_pt:.1f}x{o.measured_h_pt:.1f}pt "
            f"in {o.box_w_pt:.1f}x{o.box_h_pt:.1f}pt)"
        )
    for child in n.children:  # type: ignore[attr-defined]
        _print_layout_node(console, child, depth + 1)


@style_app.command("list")
def style_list(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """List the installed style packs (spec §3.7)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report = facade.list_styles()
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok:
            _print_diagnostics(console, report.diagnostics, quiet)
        elif not report.styles:
            console.print("[dim]no style packs installed[/dim]")
        else:
            for pack in report.styles:
                console.print(
                    f"[cyan]{_esc(pack.name)}[/cyan]@{pack.version} "
                    f"[dim]palettes={len(pack.palettes)} presets={len(pack.effect_presets)} "
                    f"roles={len(pack.roles)}[/dim]"
                )
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


@style_app.command("inspect")
def style_inspect(
    name: str = typer.Argument(..., help="Style reference (name or name@version)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Show a style pack's palettes, fonts, effect presets, and role defaults."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report = facade.inspect_style(name)
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok or report.style is None:
            _print_diagnostics(console, report.diagnostics, quiet)
        else:
            _print_style_summary(console, report.style)
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


def _print_style_summary(console: Console, style: object) -> None:
    s = style  # StyleSummary
    console.print(f"[bold]{_esc(s.name)}[/bold]@{s.version}")  # type: ignore[attr-defined]
    if s.palettes:  # type: ignore[attr-defined]
        console.print("[bold]palettes[/bold]:")
        for pname, colors in s.palettes.items():  # type: ignore[attr-defined]
            console.print(f"  [cyan]{_esc(pname)}[/cyan]: {_esc(', '.join(colors))}")
    if s.fonts:  # type: ignore[attr-defined]
        console.print("[bold]fonts[/bold]:")
        for role, families in s.fonts.items():  # type: ignore[attr-defined]
            console.print(f"  [cyan]{_esc(role)}[/cyan]: {_esc(', '.join(families))}")
    if s.effect_presets:  # type: ignore[attr-defined]
        console.print("[bold]effect presets[/bold]:")
        for pname, spec in s.effect_presets.items():  # type: ignore[attr-defined]
            console.print(f"  [cyan]{_esc(pname)}[/cyan]: {_esc(str(spec))}")
    if s.roles:  # type: ignore[attr-defined]
        console.print("[bold]roles[/bold]:")
        for role, fields in s.roles.items():  # type: ignore[attr-defined]
            console.print(f"  [cyan]{_esc(role)}[/cyan]: {_esc(str(fields))}")


def main() -> None:
    """Console-script entry point."""
    _force_utf8_stdout()
    app()


if __name__ == "__main__":
    main()

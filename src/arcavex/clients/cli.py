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
    DiffReport,
    DoctorReport,
    ExtensionActionReport,
    ExtensionListReport,
    Facade,
    FontListReport,
    LayoutReport,
    McpInstallReport,
    PatchOp,
    PreviewResult,
    ProjectStatusReport,
    RerunReport,
    RunListReport,
    RunReport,
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
effects_app = typer.Typer(add_completion=False, help="Effect catalog commands.")
app.add_typer(effects_app, name="effects")
project_app = typer.Typer(add_completion=False, help="Project lifecycle commands.")
app.add_typer(project_app, name="project")
data_app = typer.Typer(add_completion=False, help="Project data authoring commands.")
app.add_typer(data_app, name="data")
asset_app = typer.Typer(add_completion=False, help="Asset ingest/annotation commands.")
app.add_typer(asset_app, name="asset")
mcp_app = typer.Typer(add_completion=False, help="MCP authoring server (spec §6.2).")
app.add_typer(mcp_app, name="mcp")
editor_app = typer.Typer(help="Semantic project editing: apply, undo, redo, history.")
app.add_typer(editor_app, name="editor")
ext_app = typer.Typer(add_completion=False, help="Trusted local extension commands (spec §7).")
app.add_typer(ext_app, name="ext")
font_app = typer.Typer(add_completion=False, help="Font install/inspect commands (spec §4.3).")
app.add_typer(font_app, name="font")
skill_app = typer.Typer(
    add_completion=False, help="Install the bundled design skill into an AI assistant."
)
app.add_typer(skill_app, name="skill")
desktop_app = typer.Typer(add_completion=False, help="Desktop engine compatibility commands.")
app.add_typer(desktop_app, name="desktop")


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
# ARC-AST-* = missing/undecodable asset; MISSING_FONT_CODE = font family not loaded;
# ARC-RND-030 = the file 'font add' was pointed at does not exist, which is the same
# "a named input is not there" class as a missing asset and so shares its exit code.
# ARC-MCP-002 = an AI host named with --target is not installed on this machine: the same class.
_MISSING_CODES = {"ARC-TPL-001", MISSING_FONT_CODE, "ARC-RND-030", "ARC-MCP-002"}
_MISSING_PREFIXES = ("ARC-AST",)
# Resource-limit codes that map to exit 4: the expression budget, the repeat iteration cap, and
# the per-render surface budgets (dimension/pixels/memory/wall-clock, spec §8.3).
_BUDGET_CODES = {
    BUDGET_CODE,
    "ARC-TPL-063",
    "ARC-RND-020",
    "ARC-RND-021",
    "ARC-RND-022",
    "ARC-RND-023",
}


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


def _parse_scalar(text: str) -> object:
    """Parse a CLI value as JSON (numbers, booleans, null, lists) or fall back to a string.

    So ``--value 42`` sets an int and ``--value '#fff'`` (invalid JSON) stays the string
    ``"#fff"`` — the same coercion an MCP client gets by passing a typed JSON value.
    """
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


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
    template: Path | None = typer.Argument(
        None, help="Template YAML file. Omit to render the current project (project mode)."
    ),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    locale: str | None = typer.Option(
        None, "--locale", "-l", help="Locale name (application is Phase 2)."
    ),
    style: str | None = typer.Option(
        None, "--style",
        help="Style pack to apply ('name@version' or './file.yaml'); overrides the template's "
        "'style:' opt-in.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output path; the extension (.png/.jpg/.jpeg/.webp/.pdf) selects the format. "
        "Defaults to '<template-stem>.<format>.png' in the CWD.",
    ),
    project: Path | None = typer.Option(
        None, "--project", help="Project directory (project mode); overrides upward discovery."
    ),
    record: bool = typer.Option(
        False, "--record", help="Write a recorded run manifest (direct mode); always on in "
        "project mode."
    ),
    dpi: int | None = typer.Option(None, "--dpi", help="Override render DPI."),
    quality: int | None = typer.Option(
        None, "--quality", help="Lossy encoder quality 1-100 (JPEG, lossy WebP; default 90). "
        "Ignored for PNG/PDF.", min=1, max=100,
    ),
    lossless: bool = typer.Option(
        False, "--lossless", help="Encode WebP losslessly (ignored for other formats)."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="Overlay node bounds, ids, baselines, and the safe-area margin."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human diagnostics."),
) -> None:
    """Render a template to an image or PDF, or (no template) the current project's runs."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    # Project mode: no template argument means "render the discovered project" (§6.1.2).
    if template is None:
        report = facade.render_project(
            project=project, formats=[format_name] if format_name else None,
            locales=[locale] if locale else None, dpi=dpi,
        )
        _emit_run_report(console, report, json_out, quiet)
        raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))
    if record:
        report = facade.record_render(
            template, data=data, format_name=format_name, locale=locale, style=style, dpi=dpi
        )
        _emit_run_report(console, report, json_out, quiet)
        raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))
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
        style=style,
        output=output,
        dpi=dpi,
        debug=debug,
        quality=quality,
        lossless=lossless,
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
            # The structured output_path is absolute for readers elsewhere; a person at the
            # prompt is told the name they typed, or the inferred name they were just shown.
            shown = str(output) if output is not None else result.inferred.get("output")
            console.print(
                f"[green]Rendered[/green] {_esc(shown or result.output_path)}", soft_wrap=True
            )
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


@app.command()
def validate(
    template: Path | None = typer.Argument(
        None, help="Template YAML file. Omit to validate the current project (project mode)."
    ),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    locale: str | None = typer.Option(
        None, "--locale", "-l", help="Locale name (application is Phase 2)."
    ),
    style: str | None = typer.Option(
        None, "--style",
        help="Style pack to apply ('name@version' or './file.yaml'); overrides the template's "
        "'style:' opt-in.",
    ),
    project: Path | None = typer.Option(
        None, "--project", help="Project directory (project mode); overrides upward discovery."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human diagnostics."),
) -> None:
    """Validate a template, or (with no template) the current project, without rendering."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    # Project mode: no template argument means "validate the discovered project" (DX-1),
    # mirroring render's project-mode split — its template + data + overrides across formats.
    if template is None:
        result = facade.validate_project(
            project=project, formats=[format_name] if format_name else None,
            locales=[locale] if locale else None,
        )
        diagnostics = list(result.diagnostics)
        ok = result.ok
    else:
        diagnostics = facade.validate_template(
            template=template, data=data, format_name=format_name, locale=locale, style=style
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


@editor_app.command("apply")
def editor_apply(
    file: Path = typer.Argument(
        ..., help="A JSON file holding one semantic transaction, or '-' for stdin."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Execute one semantic transaction; a refusal reports conflicts or diagnostics."""
    import json as json_module
    import sys as sys_module

    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    raw = sys_module.stdin.read() if str(file) == "-" else file.read_text(encoding="utf-8")
    try:
        payload = json_module.loads(raw)
    except ValueError as error:
        console.print(f"[red]Not valid JSON:[/red] {error}")
        raise typer.Exit(EXIT_VALIDATION) from error
    report = facade.editor_apply(payload)
    _finish_editor_command(report, console, json_out, quiet)


@editor_app.command("undo")
def editor_undo(
    project: Path | None = typer.Option(None, "--project", "-p", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Restore the project state before its newest applied history entry."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.editor_undo(project or Path.cwd())
    _finish_editor_command(report, console, json_out, quiet)


@editor_app.command("redo")
def editor_redo(
    project: Path | None = typer.Option(None, "--project", "-p", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Re-apply the oldest undone history entry."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.editor_redo(project or Path.cwd())
    _finish_editor_command(report, console, json_out, quiet)


@editor_app.command("history")
def editor_history(
    project: Path | None = typer.Option(None, "--project", "-p", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Show the undo/redo timeline and whether an external edit branched it."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.editor_history(project or Path.cwd())
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if not quiet:
            for entry in report.entries:
                console.print(f"{entry.created_at:%H:%M:%S} {entry.actor.id}: {entry.summary}")
            console.print(
                f"undo: {'yes' if report.can_undo else 'no'} · "
                f"redo: {'yes' if report.can_redo else 'no'}"
                + (" · branched by an external edit" if report.branched_by_external_edit else "")
            )
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


def _finish_editor_command(report, console: Console, json_out: bool, quiet: bool) -> None:  # noqa: ANN001
    """Shared tail for apply/undo/redo: print, then exit by the report's outcome."""
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if not quiet and report.ok:
            if report.queued_command_id is not None:
                console.print(f"[yellow]Queued for review[/yellow] as {report.queued_command_id}")
            else:
                changed = ", ".join(entry.path for entry in report.changed) or "nothing"
                console.print(f"[green]Applied[/green] · changed {changed}")
        if not quiet and not report.ok and report.conflict is not None:
            moved = ", ".join(entry.path for entry in report.conflict.changed) or "unknown files"
            console.print(f"[red]Conflict[/red]: the project changed underneath you ({moved})")
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


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
        # Escape the detail: it embeds a precedence source in brackets (e.g. "[default
        # (~/.arcavex)]") that Rich would otherwise parse as markup and silently strip, hiding
        # which config layer a value came from — the very thing the paths/config rows report.
        table.add_row(
            check.name, marks.get(check.status, check.status), _rich_escape(check.detail)
        )
    console.print(table)
    for check in report.checks:
        if check.status != "ok" and check.hint:
            console.print(f"  [dim]hint ({check.name}):[/dim] {check.hint}")


@desktop_app.command("handshake")
def desktop_handshake(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
) -> None:
    """Report engine identity, compatibility versions, paths, capabilities, and health."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet=False)
    report = facade.engine_handshake()
    if json_out:
        _emit_json(report)
    else:
        identity = report.identity
        console.print(f"[bold]Arcavex[/bold] engine {identity.engine_version}")
        console.print(f"MCP contract: {report.mcp_contract_version}")
        console.print(f"IR accepted: {', '.join(report.accepted_ir_versions)}")
        console.print(f"IR produced: {report.produced_ir_version}")
        console.print(f"Extension SDK: {report.extension_sdk_version}")
        console.print(f"Arcavex home: {report.paths.home}")
    raise typer.Exit(EXIT_OK if report.ok else EXIT_MISSING)


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
    template: Path | None = typer.Argument(
        None, help="Template file or directory. Omit to preview the current project (project mode)."
    ),
    data: Path | None = typer.Option(None, "--data", "-d", help="Path to the data YAML file."),
    format_name: str | None = typer.Option(None, "--format", "-f", help="Format name."),
    locale: str | None = typer.Option(None, "--locale", "-l", help="Locale name."),
    style: str | None = typer.Option(
        None, "--style",
        help="Style pack to apply ('name@version' or './file.yaml'); overrides the template's "
        "'style:' opt-in.",
    ),
    project: Path | None = typer.Option(
        None, "--project", help="Project directory (project mode); overrides upward discovery."
    ),
    watch: bool = typer.Option(False, "--watch", help="Re-render on every dependent-file save."),
    dpi: int | None = typer.Option(None, "--dpi", help="Override render DPI."),
    debug: bool = typer.Option(False, "--debug", help="Overlay node bounds, ids, and baselines."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human diagnostics."),
) -> None:
    """Preview a template to a stable path (with --watch, keep re-rendering), or the project."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    # Project mode: no template argument previews the discovered project across its targets (DX-1).
    if template is None:
        report = facade.preview_project(
            project=project, formats=[format_name] if format_name else None,
            locales=[locale] if locale else None, dpi=dpi,
        )
        if json_out:
            _emit_json(report)
        elif not quiet:
            if not report.ok and not report.previews:
                _print_diagnostics(console, report.diagnostics, quiet)
            for res in report.previews:
                _print_preview_line(console, res, quiet, watching=False)
        all_diags = [d for res in report.previews for d in res.diagnostics] or report.diagnostics
        raise typer.Exit(_exit_code_for(all_diags, report.ok))
    if watch:
        _run_preview_watch(
            facade, console, template, data, format_name, locale, style, dpi, quiet, debug
        )
        raise typer.Exit(EXIT_OK)  # Ctrl+C / stop exits cleanly
    result = facade.render_preview(
        template, data, format_name, locale=locale, style=style, dpi=dpi, debug=debug
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
    style: str | None,
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
            locale=locale, style=style, debug=debug, stop_event=stop_event,
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
        # The path comes first, alone on its line, and is never folded by Rich: a person pastes it
        # into a viewer and an assistant reads it back, and in an 80-column terminal it used to
        # trail the timings and wrap mid-filename. soft_wrap leaves any folding to the terminal,
        # which keeps the characters contiguous for copy and paste.
        console.print(_esc(res.output_path or ""), soft_wrap=True)
        # In one-shot mode there is no change to report, so drop the watch-only 'changed='.
        prefix = f"changed={_esc(res.changed_file)} " if (watching and res.changed_file) else ""
        console.print(
            f"{prefix}compile={res.compile_ms:.1f}ms render={res.render_ms:.1f}ms",
            soft_wrap=True,
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
    style: str | None = typer.Option(
        None, "--style",
        help="Style pack to apply ('name@version' or './file.yaml'); overrides the template's "
        "'style:' opt-in.",
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
    result = facade.check_template(template, format_name, locale, style)
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
            if report.locales:
                console.print("[bold]locales[/bold]:")
                for loc in report.locales:
                    bits = [b for b in (loc.direction, loc.digits) if b]
                    extras = [x for x in (
                        "fonts" if loc.has_fonts else None,
                        "patch" if loc.has_patch else None,
                    ) if x]
                    detail = ", ".join(bits + extras)
                    console.print(f"  {_esc(loc.name)}{f' ({_esc(detail)})' if detail else ''}")
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


@template_app.command("patch")
def template_patch(
    template: Path = typer.Argument(..., help="Template file or directory to patch in place."),
    set_path: str | None = typer.Option(
        None, "--set", help="Set 'nodes.<id>[.<field>]' to --value."
    ),
    value: str | None = typer.Option(
        None, "--value", help="Value for --set (parsed as JSON, else a string)."
    ),
    remove_path: str | None = typer.Option(
        None, "--remove", help="Remove the node or field at 'nodes.<id>[.<field>]'."
    ),
    insert_before: str | None = typer.Option(
        None, "--insert-before", help="Insert --node before 'nodes.<id>'."
    ),
    insert_after: str | None = typer.Option(
        None, "--insert-after", help="Insert --node after 'nodes.<id>'."
    ),
    node: str | None = typer.Option(
        None, "--node", help="JSON node mapping for --insert-before/--insert-after."
    ),
    ops_file: Path | None = typer.Option(
        None, "--ops-file", help="A JSON array of patch ops (overrides the single-op flags)."
    ),
    base_sha256: str | None = typer.Option(
        None, "--base-sha256", help="Reject the patch if the file changed (from a prior inspect)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Apply path-addressed set/remove/insert ops to a template on disk (comment-preserving).

    The AI mutation contract (spec §4.1.4), also reachable from the CLI: each op addresses a
    stable node id. Pass one op via the flags, or a batch via --ops-file.
    """
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    node_map = _parse_scalar(node) if node is not None else None
    if ops_file is not None:
        try:
            raw_ops = json.loads(ops_file.read_text(encoding="utf-8"))
            ops = [PatchOp.model_validate(o) for o in raw_ops]
        except (ValueError, TypeError, OSError) as exc:
            console.print(f"[red]could not read --ops-file[/red]: {_esc(exc)}")
            raise typer.Exit(EXIT_USAGE) from exc
    else:
        op = PatchOp(
            set=set_path,
            value=_parse_scalar(value) if (set_path is not None and value is not None) else None,
            remove=remove_path,
            insert_before=insert_before,
            insert_after=insert_after,
            node=node_map if isinstance(node_map, dict) else None,
        )
        if not any((set_path, remove_path, insert_before, insert_after)):
            console.print(
                "[red]nothing to patch[/red]: pass one of --set/--remove/--insert-before/"
                "--insert-after, or --ops-file."
            )
            raise typer.Exit(EXIT_USAGE)
        ops = [op]
    facade = _build_facade_or_exit(console, quiet)
    result = facade.patch_template(template, ops, base_sha256)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(
                f"[green]Patched[/green] {result.path} ({result.applied} op(s), "
                f"sha256 {result.sha256})"
            )
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


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
        _print_overlaps(console, report)
    console.print(f"[bold]coverage[/bold]: {report.covered_fraction:.0%} of canvas")
    if report.free_regions:
        console.print("[bold]free regions[/bold] (empty horizontal bands):")
        for r in report.free_regions:
            console.print(
                f"  ({r[0]:.1f}, {r[1]:.1f}, {r[2]:.1f}, {r[3]:.1f})pt"
            )
    for warn in report.warnings:
        console.print(f"[yellow]WARN {warn.code}[/yellow] {_esc(warn.message)}")


def _rect_pt(rect: tuple[float, float, float, float]) -> str:
    return f"({rect[0]:.1f}, {rect[1]:.1f}, {rect[2]:.1f}, {rect[3]:.1f})pt"


def _print_overlaps(console: Console, report: LayoutReport) -> None:
    """Print sibling overlaps with effect spill demoted below content collisions.

    A halo is one node's shadow or tear reaching over its neighbour — usually the intended look.
    Listing it alongside a real collision is what made the real one impossible to spot, so the
    ``content`` overlaps get the heading and the ``halo`` ones a dimmed, indented subsection.
    """
    content = [ov for ov in report.overlaps if ov.kind == "content"]
    halo = [ov for ov in report.overlaps if ov.kind == "halo"]
    console.print(
        f"[bold]overlaps[/bold]: {len(content)} content, {len(halo)} effect spill"
    )
    for ov in content:
        console.print(f"  {_esc(ov.a)} ∩ {_esc(ov.b)} at {_rect_pt(ov.rect_pt)}")
    if not content:
        console.print("  [dim]no content collisions[/dim]")
    if halo:
        console.print("  [dim]effect spill (paint bounds only — usually intended):[/dim]")
        for ov in halo:
            console.print(
                f"    [dim]{_esc(ov.a)} ∩ {_esc(ov.b)} at {_rect_pt(ov.rect_pt)}[/dim]"
            )


def _print_layout_node(console: Console, node: object, depth: int) -> None:
    n = node  # LayoutNodeReport
    pad = "  " * depth
    console.print(
        f"{pad}[cyan]{_esc(n.id)}[/cyan] [dim]{n.kind}[/dim] "  # type: ignore[attr-defined]
        f"bounds {_rect_pt(n.bounds_pt)}"  # type: ignore[attr-defined]
    )
    # Paint bounds get their own line rather than a suffix: a halo overlap's rect comes from
    # this box, so it has to be readable, and at ~80 columns a second rect on the node line
    # wraps mid-number, which makes the coordinates unreadable.
    console.print(
        f"{pad}  [dim]paint {_rect_pt(n.paint_bounds_pt)}[/dim]"  # type: ignore[attr-defined]
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


@effects_app.command("list")
def effects_list(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """List the registered effects, their category, and each param's type/default/range."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report = facade.list_effects()
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok:
            _print_diagnostics(console, report.diagnostics, quiet)
        else:
            for effect in report.effects:
                _print_effect_info(console, effect)
    raise typer.Exit(EXIT_OK if report.ok else EXIT_VALIDATION)


@effects_app.command("inspect")
def effects_inspect(
    name: str = typer.Argument(..., help="Effect name, e.g. 'drop-shadow'."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Show one effect's category and full parameter schema."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report = facade.list_effects()
    match = next((e for e in report.effects if e.name == name), None)
    if match is None:
        if not quiet:
            available = ", ".join(e.name for e in report.effects) or "(none)"
            console.print(
                f"[red]unknown effect[/red] {_esc(name)}\n"
                f"  [dim]registered effects:[/dim] {_esc(available)}"
            )
        raise typer.Exit(EXIT_VALIDATION)
    if json_out:
        _emit_json(match)
    elif not quiet:
        _print_effect_info(console, match)
    raise typer.Exit(EXIT_OK)


def _print_effect_info(console: Console, effect: object) -> None:
    e = effect  # EffectInfo
    console.print(
        f"[cyan]{_esc(e.name)}[/cyan] [dim]{e.category}[/dim]"  # type: ignore[attr-defined]
    )
    for p in e.params:  # type: ignore[attr-defined]
        req = "required" if p.required else f"default={p.default!r}"
        rng = f" [{p.constraint}]" if p.constraint else ""
        console.print(f"  {_esc(p.name)}: {p.type} ({req}){_esc(rng)}")


def _emit_run_report(
    console: Console, report: RunReport, json_out: bool, quiet: bool
) -> None:
    """Print a recorded-render result (run dir + outputs) in JSON or human form."""
    if json_out:
        _emit_json(report)
        return
    _print_diagnostics(console, report.diagnostics, quiet)
    if report.ok and not quiet:
        console.print(f"[green]Recorded run[/green] {report.run_id}")
        for out in report.outputs:
            console.print(f"  {out}")


# ----------------------------------------------------------------------------- projects
@project_app.command("new")
def project_new(
    target: Path = typer.Argument(..., help="Directory to create the project in."),
    template: str = typer.Option(
        ..., "--template", "-t", help="Template reference: 'name@version' or a path."
    ),
    name: str | None = typer.Option(None, "--name", help="Project name (defaults to dir name)."),
    style: str | None = typer.Option(None, "--style", help="Style pack reference."),
    format_name: list[str] = typer.Option(
        None, "--format", "-f", help="Restrict to these formats (repeatable)."
    ),
    locale: list[str] = typer.Option(
        None, "--locale", "-l", help="Restrict to these locales (repeatable)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Scaffold a renderable project pinning a template version."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.create_project(
        target, name or target.name, template, style=style,
        formats=list(format_name or []) or None, locales=list(locale or []) or None,
    )
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(
                f"[green]Created project[/green] {result.name} at {result.path} "
                f"(template {result.template}, formats {', '.join(result.formats)})"
            )
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


@project_app.command("clone")
def project_clone(
    target: Path = typer.Argument(..., help="Directory to clone the project into."),
    name: str | None = typer.Option(
        None, "--name", help="New project name (defaults to dir name)."
    ),
    project: Path | None = typer.Option(None, "--project", help="Source project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Clone the current (or --project) project into a new directory, reset to draft."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.clone_project(target, name or target.name, project=project)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(f"[green]Cloned[/green] to {result.path} (status {result.status})")
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


@project_app.command("set-status")
def project_set_status(
    status_value: str = typer.Argument(..., help="draft | review | approved | published."),
    project: Path | None = typer.Option(None, "--project", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Set the current project's lifecycle status."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.set_project_status(status_value, project=project)
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok and not quiet:
            console.print(f"[green]Status[/green] {report.name} -> {report.status}")
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@project_app.command("upgrade")
def project_upgrade(
    to_version: str = typer.Option(..., "--to", help="Target template version, e.g. 1.3.0."),
    yes: bool = typer.Option(
        False, "--yes", help="Update the pin after previewing (default previews only)."
    ),
    project: Path | None = typer.Option(None, "--project", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Preview a template-version upgrade; with --yes, update the pin."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.upgrade_project(to_version, apply=yes, project=project)
    if json_out:
        _emit_json(report)
    elif not quiet:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok:
            console.print(
                f"[bold]upgrade[/bold] {report.from_version} -> {report.to_version} "
                f"({'applied' if report.applied else 'preview only'})"
            )
            if report.stale:
                console.print("[yellow]stale override paths[/yellow] (no longer resolve):")
                for s in report.stale:
                    node = f" (node {s.node_id})" if s.node_id else ""
                    console.print(f"  {_esc(s.path or s.op)}{_esc(node)} [dim]{_esc(s.op)}[/dim]")
            if report.added_nodes or report.removed_nodes:
                console.print("[bold]node changes[/bold]:")
                if report.added_nodes:
                    console.print(f"  [green]added[/green]: {_esc(', '.join(report.added_nodes))}")
                if report.removed_nodes:
                    console.print(
                        f"  [red]removed[/red]: {_esc(', '.join(report.removed_nodes))}"
                    )
            if report.outputs:
                console.print("[bold]preview diff[/bold] (current pin vs target):")
                for o in report.outputs:
                    score = "identical" if o.dssim == 0.0 else (
                        "shape differs" if o.dssim is None else f"dssim {o.dssim:.4f}"
                    )
                    note = "" if o.patch_applied else " [dim](override dropped: stale)[/dim]"
                    console.print(f"  {_esc(o.name)}: {score}{note}")
            if not report.applied:
                console.print("[dim]re-run with --yes to update the pin[/dim]")
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@app.command()
def status(
    project: Path | None = typer.Option(None, "--project", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Show the current project's manifest and recorded-run count."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report: ProjectStatusReport = facade.project_status(project=project)
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok:
            _print_diagnostics(console, report.diagnostics, quiet)
        else:
            console.print(f"[bold]{_esc(report.name)}[/bold] [dim]({report.status})[/dim]")
            console.print(f"  template: {report.template}")
            console.print(f"  style: {report.style or '-'}")
            console.print(f"  formats: {', '.join(report.formats) or '-'}")
            console.print(f"  locales: {', '.join(report.locales) or '-'}")
            console.print(f"  data: {report.data or '-'}")
            console.print(f"  runs recorded: {report.runs}")
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@app.command("list-runs")
def list_runs(
    project: Path | None = typer.Option(None, "--project", help="Project directory."),
    path: Path | None = typer.Option(
        None, "--path",
        help="List recorded runs under this outputs/ directory (direct-mode --record runs), "
        "instead of the current project.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """List recorded runs (project's, or with --path a direct-mode outputs dir), newest first."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report: RunListReport = facade.list_runs(project=project, path=path)
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok:
            _print_diagnostics(console, report.diagnostics, quiet)
        elif not report.runs:
            console.print("[dim]no recorded runs[/dim]")
        else:
            for run in report.runs:
                console.print(
                    f"[cyan]{run.run_id}[/cyan] [dim]{run.kind}[/dim] "
                    f"{len(run.outputs)} output(s) [dim]{run.engine_version} {run.platform}[/dim]"
                )
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@app.command()
def rerun(
    run_dir: Path = typer.Argument(..., help="A recorded run directory (outputs/<run>)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Reproduce a recorded run into a new run directory (byte-identical on match).

    Takes the run directory, or the bare run id that ``list-runs`` prints — the two are the same
    string only because the id happens to name the directory under ``outputs/``, which nothing
    says out loud. Passing what the listing showed used to fail with "no run manifest".
    """
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    resolved = run_dir
    if not (run_dir / "manifest.json").is_file():
        candidate = Path.cwd() / "outputs" / run_dir.name
        if (candidate / "manifest.json").is_file():
            resolved = candidate
    report: RerunReport = facade.rerun(resolved)
    if json_out:
        _emit_json(report)
    elif not quiet:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok:
            if report.reproduced:
                console.print(
                    f"[green]Reproduced[/green] {report.source_run} -> {report.run_id} "
                    "(byte-identical)"
                )
            else:
                reason = []
                if not report.engine_match:
                    reason.append("engine version differs")
                if not report.platform_match:
                    reason.append("platform differs")
                if report.mismatches:
                    reason.append(f"{len(report.mismatches)} output(s) differ")
                console.print(
                    f"[yellow]Rendered[/yellow] {report.run_id} but did not claim exact "
                    f"reproduction ({'; '.join(reason) or 'unknown'})"
                )
                # Name the input(s) that changed on disk, so a same-engine/platform failure is
                # explained rather than just flagged (CR-3/DX-3).
                if report.drift:
                    console.print(
                        f"  [dim]changed on disk:[/dim] {_esc(', '.join(report.drift))}"
                    )
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@app.command()
def diff(
    run_a: Path = typer.Argument(..., help="First run directory."),
    run_b: Path = typer.Argument(..., help="Second run directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Diff two recorded runs: per-output pixels/perceptual plus provenance changes."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report: DiffReport = facade.diff_runs(run_a, run_b)
    if json_out:
        _emit_json(report)
    elif not quiet:
        if not report.ok:
            _print_diagnostics(console, report.diagnostics, quiet)
        else:
            _print_diff(console, report)
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


def _print_diff(console: Console, report: DiffReport) -> None:
    console.print(f"[bold]diff[/bold] {report.run_a} .. {report.run_b}")
    console.print("[bold]outputs[/bold]:")
    for o in report.outputs:
        if not (o.in_a and o.in_b):
            where = "only in A" if o.in_a else "only in B"
            console.print(f"  {_esc(o.name)}: [yellow]{where}[/yellow]")
        elif o.identical:
            console.print(f"  {_esc(o.name)}: [green]identical[/green]")
        else:
            score = "shape differs" if o.dssim is None else f"dssim {o.dssim:.4f}"
            console.print(f"  {_esc(o.name)}: [yellow]{score}[/yellow]")
    if report.metadata:
        console.print("[bold]metadata changes[/bold]:")
        for m in report.metadata:
            console.print(f"  {_esc(m.field)}: {_esc(m.a)} -> {_esc(m.b)}")
    else:
        console.print("[dim]no metadata changes[/dim]")


@app.command()
def batch(
    patterns: list[str] = typer.Argument(..., help="Glob(s) matching project directories."),
    jobs: int = typer.Option(1, "--jobs", "-j", help="Parallel render jobs (output == serial)."),
    dpi: int | None = typer.Option(None, "--dpi", help="Override render DPI."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Render every matched project's formats × locales in parallel jobs."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.batch_render(list(patterns), jobs=jobs, dpi=dpi)
    if json_out:
        _emit_json(report)
    elif not quiet:
        _print_diagnostics(console, report.diagnostics, quiet)
        for entry in report.entries:
            mark = "[green]ok[/green]" if entry.ok else "[red]failed[/red]"
            console.print(f"  {mark} {_esc(entry.project)} ({len(entry.outputs)} output(s))")
            if not entry.ok:
                _print_diagnostics(console, entry.diagnostics, quiet)
        # Aggregate tally so a large batch's health is legible without counting rows (DX-10).
        n_ok = sum(1 for e in report.entries if e.ok)
        n_failed = len(report.entries) - n_ok
        color = "green" if report.ok else "red"
        console.print(
            f"[{color}]Batch complete[/{color}] {n_ok} ok / {n_failed} failed "
            f"({len(report.entries)} project(s), {report.jobs} job(s))"
        )
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@template_app.command("publish")
def template_publish(
    template: Path = typer.Argument(..., help="Template directory to publish."),
    name: str = typer.Option(..., "--name", help="Library template name."),
    version: str = typer.Option(..., "--version", help="Version to publish, e.g. 1.0.0."),
    default: bool = typer.Option(
        True, "--default/--no-default", help="Point the default alias at this version."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Publish a template directory into the library as an immutable version."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.publish_template(template, name, version, set_default=default)
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok and not quiet:
            console.print(
                f"[green]Published[/green] {report.name}@{report.version} "
                f"(default {report.default}) at {report.path}"
            )
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@template_app.command("detach")
def template_detach(
    project: Path | None = typer.Option(None, "--project", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Copy the project's library template into the project (disables version upgrades)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.detach_template(project=project)
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok and not quiet:
            console.print(f"[green]Detached[/green] into {report.path}")
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@data_app.command("set")
def data_set(
    keypath: str = typer.Argument(..., help="Dotted keypath, e.g. 'title' or 'contact.email'."),
    value: str = typer.Argument(..., help="Value (parsed as JSON, else a string)."),
    project: Path | None = typer.Option(None, "--project", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Set a single value in the current project's data, then revalidate (spec §3.7)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.set_data(keypath, _parse_scalar(value), project=project)
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok and not quiet:
            console.print(f"[green]Set[/green] {keypath} in {report.path}")
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@data_app.command("import")
def data_import(
    file: Path | None = typer.Argument(
        None, help="YAML data document to merge. Omit to read from stdin."
    ),
    locale: str | None = typer.Option(
        None, "--locale", "-l", help="Locale to compile-validate against after the merge."
    ),
    project: Path | None = typer.Option(None, "--project", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Merge a YAML data document into the current project's data (overlay semantics, §3.7)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    if file is not None:
        try:
            yaml_text = file.read_text(encoding="utf-8")
        except OSError as exc:
            console.print(f"[red]could not read[/red] {_esc(file)}: {_esc(exc)}")
            raise typer.Exit(EXIT_USAGE) from exc
    else:
        yaml_text = sys.stdin.read()
    facade = _build_facade_or_exit(console, quiet)
    report = facade.import_data(yaml_text, locale=locale, project=project)
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok and not quiet:
            console.print(f"[green]Imported[/green] into {report.path}")
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@asset_app.command("add")
def asset_add(
    source: Path = typer.Argument(..., help="Image file to ingest into the workspace CAS."),
    project: Path | None = typer.Option(None, "--project", help="Project directory."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Ingest an image into the content-addressed store and report its reference (§4.7)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.add_asset(source, project=project)
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok and report.asset is not None and not quiet:
            a = report.asset
            console.print(
                f"[green]Ingested[/green] {a.sha256} ({a.mime}, {a.width}x{a.height}, "
                f"{a.bytes} bytes)"
            )
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@asset_app.command("annotate")
def asset_annotate(
    sha256: str = typer.Argument(..., help="The ingested asset's content hash."),
    set_values: list[str] = typer.Option(
        None, "--set", help="An annotation as 'key=value' (repeatable; value parsed as JSON)."
    ),
    annotations_json: str | None = typer.Option(
        None, "--annotations", help="A JSON object of annotations (merged with any --set)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Write sidecar annotations (facing/focal_point/tags) onto an ingested asset (§4.7)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    annotations: dict[str, object] = {}
    if annotations_json is not None:
        parsed = _parse_scalar(annotations_json)
        if not isinstance(parsed, dict):
            console.print("[red]--annotations must be a JSON object[/red]")
            raise typer.Exit(EXIT_USAGE)
        annotations.update(parsed)
    for item in set_values or []:
        if "=" not in item:
            console.print(f"[red]--set expects key=value[/red], got {_esc(item)}")
            raise typer.Exit(EXIT_USAGE)
        key, _, raw = item.partition("=")
        annotations[key] = _parse_scalar(raw)
    if not annotations:
        console.print("[red]nothing to annotate[/red]: pass --set key=value or --annotations.")
        raise typer.Exit(EXIT_USAGE)
    facade = _build_facade_or_exit(console, quiet)
    report = facade.annotate_asset(sha256, annotations)
    if json_out:
        _emit_json(report)
    else:
        _print_diagnostics(console, report.diagnostics, quiet)
        if report.ok and report.asset is not None and not quiet:
            console.print(f"[green]Annotated[/green] {report.asset.sha256}")
    raise typer.Exit(_exit_code_for(report.diagnostics, report.ok))


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Start the MCP authoring server over stdio (spec §6.2).

    The server mirrors the service API as MCP tools — no capability is reachable only here — and
    speaks stdio only (no network). It blocks until the client disconnects.
    """
    from arcavex.clients.mcp_server import serve

    serve()


@mcp_app.command("tools")
def mcp_tools(
    json_out: bool = typer.Option(False, "--json", help="Emit the tool catalog as JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
) -> None:
    """List the MCP tool catalog (names, descriptions, and input/output schemas)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    from arcavex.clients.mcp_server import build_mcp_server, catalog_json, tool_catalog

    if json_out:
        typer.echo(catalog_json())
    else:
        for tool in tool_catalog(build_mcp_server()):
            console.print(f"[cyan]{_esc(tool['name'])}[/cyan] — {_esc(tool['description'])}")
    raise typer.Exit(EXIT_OK)


@mcp_app.command("install")
def mcp_install(
    target: list[str] = typer.Option(
        [],
        "--target",
        "-t",
        help="Host to register with: claude-code, claude-desktop, codex ('desktop' and 'chatgpt' "
        "are aliases). Repeatable. Default: every host present on this machine.",
    ),
    list_only: bool = typer.Option(
        False,
        "--list",
        help="Show every host and whether the server is registered there; write nothing.",
    ),
    print_only: bool = typer.Option(
        False, "--print", help="Print the snippet to paste for each host; write nothing."
    ),
    force: bool = typer.Option(
        False, "--force", help="Replace an existing 'arcavex' registration."
    ),
    command: Path | None = typer.Option(
        None,
        "--command",
        help="Register this executable instead of the running engine; the host runs it as "
        "'<PATH> mcp serve'.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Register the MCP server with Claude Code, Claude Desktop, or Codex."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    if list_only or print_only:
        report = facade.list_mcp_targets(command)
    else:
        report = facade.install_mcp(list(target) or None, command, force)
    if json_out:
        _emit_json(report)
    elif not quiet:
        _print_mcp_report(console, report, list_only=list_only, print_only=print_only)
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


# What a host needs after registering: each reads its configuration when it starts.
_MCP_NEXT_STEP = {
    "claude-code": "open a new Claude Code session",
    "claude-desktop": "quit and reopen Claude Desktop",
    "codex": "start a new Codex session",
}


def _join_command(argv: list[str]) -> str:
    """Show a command line as a person would type it (double quotes work in every shell)."""
    return " ".join(f'"{arg}"' if any(ch.isspace() for ch in arg) else arg for arg in argv)


def _print_mcp_report(
    console: Console, report: McpInstallReport, *, list_only: bool, print_only: bool
) -> None:
    """Print each host's state and what was registered, ending with what to do next."""
    if print_only:
        # The snippets go through echo, not Rich: a wrapped or markup-mangled path is not
        # something a person can paste.
        for entry in report.targets:
            console.print(
                f"[bold]{_esc(entry.label)}[/bold]  [dim]{_esc(entry.location)}[/dim]",
                soft_wrap=True,
            )
            if entry.note:
                console.print(f"[dim]{_esc(entry.note)}[/dim]", soft_wrap=True)
            typer.echo(entry.snippet.rstrip("\n"))
            typer.echo()
        typer.echo(f"command: {_join_command(report.command)}")
        return
    if report.targets:
        table = Table(box=None, pad_edge=False)
        table.add_column("target", style="bold", no_wrap=True)
        # A path folded onto two lines can still be opened; one cut with an ellipsis cannot.
        table.add_column("location", overflow="fold")
        table.add_column("state", no_wrap=True)
        for entry in report.targets:
            if not entry.available:
                state = "host not found"
            elif entry.registered:
                state = "registered"
            else:
                state = "not registered"
            table.add_row(entry.label, entry.location, state)
        console.print(table)
    if report.command:
        typer.echo(f"command: {_join_command(report.command)}")
    _print_diagnostics(console, report.diagnostics, quiet=False)
    if report.installed:
        labels = {entry.key: entry.label for entry in report.targets}
        console.print(
            f"Registered the Arcavex MCP server with {len(report.installed)} host(s):"
        )
        for key in report.installed:
            console.print(f"  {_esc(labels.get(key, key))}")
        steps = [_MCP_NEXT_STEP[key] for key in report.installed if key in _MCP_NEXT_STEP]
        if steps:
            console.print("Next: " + "; ".join(steps) + ".")
    elif not list_only and report.ok:
        console.print("Nothing to do.")


@ext_app.command("scaffold")
def ext_scaffold(
    kind: str = typer.Argument(..., help="Component kind (effect, mask, shape, …)."),
    target: Path = typer.Argument(..., help="Directory to scaffold the extension into."),
    name: str | None = typer.Option(None, "--name", help="Extension/component name."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Scaffold a new, immediately-valid extension directory of the given kind."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.scaffold_extension(kind, target, name)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(
                f"[green]Created[/green] {result.path} "
                f"({result.kind} '{result.name}') — validate, test, then add it"
            )
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


@ext_app.command("validate")
def ext_validate(
    path: Path = typer.Argument(..., help="Extension directory (containing extension.toml)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Validate an extension's manifest, compatibility, imports, determinism, and schemas."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.validate_extension(path)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            components = ", ".join(result.components) or "(none)"
            console.print(f"[green]OK[/green] {result.name} — components: {components}")
    raise typer.Exit(_exit_code_for(result.diagnostics, result.ok))


@ext_app.command("test")
def ext_test(
    path: Path = typer.Argument(..., help="Extension directory to golden-test."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Run the extension's golden fixtures in a crash-contained subprocess."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.test_extension(path)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if not quiet:
            if result.output:
                console.print(f"[dim]{_esc(result.output)}[/dim]")
            if result.passed:
                console.print(f"[green]PASS[/green] {result.name} golden test")
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


@ext_app.command("add")
def ext_add(
    path: Path = typer.Argument(..., help="Extension directory to add (validated first)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Validate and add a local extension to the Arcavex home, recorded disabled.

    Extensions are trusted local code — review one obtained from an AI or third party like any
    other dependency before enabling it (spec §7.3).
    """
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.add_extension(path)
    _emit_ext_action(console, result, json_out, quiet, "Added", "enable it next")
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


@ext_app.command("enable")
def ext_enable(
    name: str = typer.Argument(..., help="Added extension name."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Enable an added extension (its components register on the next run)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.enable_extension(name)
    _emit_ext_action(console, result, json_out, quiet, "Enabled", "active on the next run")
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


@ext_app.command("disable")
def ext_disable(
    name: str = typer.Argument(..., help="Added extension name."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Disable an added extension (deregistered on the next run)."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.disable_extension(name)
    _emit_ext_action(console, result, json_out, quiet, "Disabled", "inactive on the next run")
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


@ext_app.command("list")
def ext_list(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """List every added local extension, its enabled state, and its components."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report = facade.list_extensions()
    if json_out:
        _emit_json(report)
    elif not quiet:
        _print_ext_list(console, report)
    raise typer.Exit(EXIT_OK if report.ok else EXIT_VALIDATION)


def _emit_ext_action(
    console: Console,
    result: ExtensionActionReport,
    json_out: bool,
    quiet: bool,
    verb: str,
    tail: str,
) -> None:
    if json_out:
        _emit_json(result)
        return
    _print_diagnostics(console, result.diagnostics, quiet)
    if result.ok and not quiet:
        console.print(f"[green]{verb}[/green] {result.name} ({tail})")


def _print_ext_list(console: Console, report: ExtensionListReport) -> None:
    for diag in report.load_diagnostics:
        console.print(
            f"[yellow]load {diag.code}[/yellow] {_esc(diag.message)}"
        )
    if not report.extensions:
        console.print("[dim]no local extensions added[/dim]")
        return
    for ext in report.extensions:
        state = "[green]enabled[/green]" if ext.enabled else "[dim]disabled[/dim]"
        components = ", ".join(f"{c.kind}:{c.name}" for c in ext.components) or "(none)"
        console.print(f"[cyan]{_esc(ext.name)}[/cyan] {ext.version} {state} — {components}")


@font_app.command("list")
def font_list(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """List every font family the engine can resolve, marking bundled vs installed."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    report = facade.list_fonts()
    if json_out:
        _emit_json(report)
    elif not quiet:
        _print_font_list(console, report)
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


@font_app.command("add")
def font_add(
    path: Path = typer.Argument(..., help="Font file (.ttf) to install."),
    license_path: Path | None = typer.Option(
        None, "--license", help="Licence file to copy alongside the font (e.g. an OFL.txt)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Install a font into the Arcavex home and report the family name templates must use.

    The reported family is read from the file itself, so it is the name the engine will resolve —
    a file stem and its internal family name often differ, and 'style.font' must name the family.
    """
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.add_font(path, license_path)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(
                f"[green]Installed[/green] {_esc(result.family)} into {result.install_dir}"
            )
            console.print(
                f"  [dim]use it in a template as:[/dim] style: {{font: {_esc(result.family)}}}"
            )
            if result.license:
                console.print(f"  [dim]licence:[/dim] {result.license}")
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


@font_app.command("remove")
def font_remove(
    family: str = typer.Argument(..., help="Installed family name (not a file name)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Remove an installed font family; a family bundled with the engine is refused."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color, stderr=True)
    facade = _build_facade_or_exit(console, quiet)
    result = facade.remove_font(family)
    if json_out:
        _emit_json(result)
    else:
        _print_diagnostics(console, result.diagnostics, quiet)
        if result.ok and not quiet:
            console.print(
                f"[green]Removed[/green] {_esc(result.family)} ({len(result.files)} file(s))"
            )
    raise typer.Exit(EXIT_OK if result.ok else _exit_code_for(result.diagnostics, result.ok))


def _print_font_list(console: Console, report: FontListReport) -> None:
    if not report.ok:
        _print_diagnostics(console, report.diagnostics, quiet=False)
        return
    if not report.families:
        console.print("[dim]no font families found[/dim]")
    for info in report.families:
        # Both flags can be true (an extra weight installed for a bundled family), so the label
        # reports the union rather than picking one and hiding the other.
        tags = [t for t in ("bundled" if info.bundled else None,
                            "installed" if info.installed else None) if t]
        console.print(
            f"[cyan]{_esc(info.family)}[/cyan] [dim]{'+'.join(tags)}[/dim] "
            f"[dim]({len(info.files)} file(s))[/dim]"
        )
        for file in info.files:
            console.print(f"  [dim]{_esc(file.name)}[/dim]")
    console.print(f"[dim]install fonts into:[/dim] {report.install_dir}")
    console.print("[dim]add one with:[/dim] arcavex font add <path/to/font.ttf>")

# --------------------------------------------------------------------------- skill install
@skill_app.command("install")
def skill_install(
    target: list[str] = typer.Option(
        [],
        "--target",
        "-t",
        help="Harness to install into (claude-code, agents). Repeatable. "
        "Default: every known harness.",
    ),
    path: Path | None = typer.Option(
        None, "--path", help="Install into this directory instead of a known harness location."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing installation."),
    project: bool = typer.Option(
        False,
        "--project",
        help="Install into the current directory instead of your home directory, so the "
        "skill travels with the repository.",
    ),
    list_only: bool = typer.Option(
        False, "--list", help="Show every destination without writing anything."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress human output."),
) -> None:
    """Install the bundled design skill so an AI assistant knows how to drive Arcavex."""
    if json_out:
        _force_utf8_stdout()
    console = Console(no_color=no_color)
    facade = _build_facade_or_exit(Console(no_color=no_color, stderr=True), quiet)
    if list_only:
        report = facade.list_skill_targets(path, project)
    else:
        report = facade.install_skill(list(target) or None, path, force, project)
    if json_out:
        _emit_json(report)
    elif not quiet:
        _print_skill_report(console, report, list_only=list_only)
    raise typer.Exit(EXIT_OK if report.ok else _exit_code_for(report.diagnostics, report.ok))


def _print_skill_report(console: Console, report: object, *, list_only: bool) -> None:
    """Print install destinations and what was written."""
    targets = report.targets  # type: ignore[attr-defined]
    if targets:
        table = Table(box=None, pad_edge=False)
        table.add_column("target", style="bold")
        table.add_column("path")
        table.add_column("state")
        for entry in targets:
            state = "installed" if entry.installed else "not installed"
            if not entry.verified:
                state += " (path unverified)"
            table.add_row(entry.label, entry.path, state)
        console.print(table)
    installed = report.installed  # type: ignore[attr-defined]
    if installed:
        console.print(f"Installed {report.skill} to {len(installed)} location(s):")  # type: ignore[attr-defined]
        for where in installed:
            console.print(f"  {where}")
        console.print("Restart the assistant to pick it up.")
    elif not list_only and report.ok:  # type: ignore[attr-defined]
        console.print("Nothing to do.")


def main() -> None:
    """Console-script entry point."""
    _force_utf8_stdout()
    app()


if __name__ == "__main__":
    main()

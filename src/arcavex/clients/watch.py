"""Watch-mode preview loop for ``arcavex preview --watch`` (spec §6.1.1 / §6.3).

The loop watches the template directory (template.yaml, its sidecars, and template-relative
assets), the directories holding any out-of-tree referenced assets, and the data file, and
re-renders on every debounced change. It is factored out of the Typer command as a plain
function so it can be driven directly in tests through a stop event and an ``max_iterations``
bound, rather than by killing a subprocess (Ctrl+C handling is flaky on Windows).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from arcavex.kernel.api import Facade, PreviewResult
from arcavex.services.template.loader import resolve_template_path

# Debounce window in milliseconds: coalesce a burst of editor saves into one re-render.
_DEBOUNCE_MS = 100
# Finite rust timeout so the loop wakes periodically to honor a set stop_event promptly (a
# programmatic stop no longer waits for the next filesystem event), and Ctrl+C stays snappy.
_RUST_TIMEOUT_MS = 300


def watch_paths(
    template: Path, data: Path | None, extra_dirs: list[str] | None = None
) -> list[str]:
    """Return the filesystem paths the watch loop should observe.

    The template root directory covers template.yaml, its sidecars, and in-tree assets; the
    data file and any ``extra_dirs`` (parents of out-of-tree referenced assets, CR-9) are
    added on top. Duplicates and directories already contained in the root are dropped.
    """
    try:
        root_dir, _template_yaml = resolve_template_path(Path(template))
    except Exception:  # noqa: BLE001 - fall back to the raw path if resolution fails
        root_dir = Path(template).parent
    root_resolved = root_dir.resolve()
    paths: list[str] = [str(root_dir)]
    seen: set[str] = {str(root_resolved)}
    if data is not None:
        data_path = str(Path(data))
        if data_path not in seen:
            paths.append(data_path)
            seen.add(data_path)
    for extra in extra_dirs or []:
        resolved = str(Path(extra).resolve())
        # Skip anything already covered by the (recursively watched) template root.
        if resolved in seen or resolved.startswith(str(root_resolved)):
            continue
        if Path(extra).exists():
            paths.append(extra)
            seen.add(resolved)
    return paths


def run_watch(
    facade: Facade,
    template: Path,
    data: Path | None,
    format_name: str | None,
    dpi: int | None,
    on_result: Callable[[PreviewResult], None],
    *,
    locale: str | None = None,
    debug: bool = False,
    stop_event: threading.Event | None = None,
    max_iterations: int | None = None,
) -> None:
    """Run the save-to-preview loop, calling ``on_result`` after each render.

    The watcher is started before the initial render (CR-7): the first loop iteration — a
    ``yield_on_timeout`` tick — runs the initial render only after the filesystem watch is
    already registered, so a save landing in the old startup window is captured and re-rendered
    on the next tick instead of being lost. The loop ends when ``stop_event`` is set, when
    ``max_iterations`` change-driven re-renders have occurred, or when the watcher stops.

    Args:
        facade: The service facade.
        template: The template path (file or directory).
        data: Optional data file path.
        format_name: Optional format name.
        dpi: Optional render DPI override.
        on_result: Callback invoked with every :class:`PreviewResult` (initial and each change).
        locale: Optional locale name (application is Phase 2; requesting one is diagnosed).
        stop_event: Optional event that stops the loop when set (test/Ctrl-C seam).
        max_iterations: Optional bound on the number of change-driven re-renders (test seam).
    """
    from watchfiles import watch

    def render(changed: str | None) -> PreviewResult:
        return facade.render_preview(
            template, data, format_name, locale=locale, dpi=dpi, changed_file=changed,
            debug=debug,
        )

    asset_dirs = [
        str(Path(p).parent)
        for p in facade.collect_asset_paths(template, data, format_name, locale)
    ]
    paths = watch_paths(template, data, asset_dirs)

    started = False
    iterations = 0
    for changes in watch(
        *paths,
        stop_event=stop_event,
        debounce=_DEBOUNCE_MS,
        rust_timeout=_RUST_TIMEOUT_MS,
        yield_on_timeout=True,
    ):
        if not started:
            # The watch is now registered; render the initial preview. Any save during startup
            # arrives as a subsequent change rather than being dropped.
            started = True
            on_result(render("(initial)"))
            if stop_event is not None and stop_event.is_set():
                return
            if not changes:  # a plain startup timeout tick carried no changes
                continue
        if not changes:  # timeout tick with nothing to do
            continue
        on_result(render(_first_changed(changes)))
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return


def _first_changed(changes: set[tuple[object, str]]) -> str:
    """Return one representative changed path from a watchfiles change batch."""
    paths = sorted(path for _change, path in changes)
    return paths[0] if paths else "(unknown)"

"""Watch-mode preview loop for ``arcavex preview --watch`` (spec §6.1.1 / §6.3).

The loop watches the template directory (template.yaml, its sidecars, and template-relative
assets) plus the data file, and re-renders on every debounced change. It is factored out of the
Typer command as a plain function so it can be driven directly in tests through a stop event and
an ``max_iterations`` bound, rather than by killing a subprocess (Ctrl+C handling is flaky on
Windows).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from arcavex.kernel.api import Facade, PreviewResult
from arcavex.services.template.loader import resolve_template_path

# Debounce window in milliseconds: coalesce a burst of editor saves into one re-render.
_DEBOUNCE_MS = 100


def watch_paths(template: Path, data: Path | None) -> list[str]:
    """Return the filesystem paths the watch loop should observe."""
    try:
        root_dir, _template_yaml = resolve_template_path(Path(template))
    except Exception:  # noqa: BLE001 - fall back to the raw path if resolution fails
        root_dir = Path(template).parent
    paths = [str(root_dir)]
    if data is not None:
        paths.append(str(Path(data)))
    return paths


def run_watch(
    facade: Facade,
    template: Path,
    data: Path | None,
    format_name: str | None,
    dpi: int | None,
    on_result: Callable[[PreviewResult], None],
    *,
    stop_event: threading.Event | None = None,
    max_iterations: int | None = None,
) -> None:
    """Run the save-to-preview loop, calling ``on_result`` after each render.

    An initial render happens immediately; thereafter each debounced batch of changes triggers
    one incremental re-render. The loop ends when ``stop_event`` is set, when ``max_iterations``
    re-renders have occurred, or when the underlying watcher stops.

    Args:
        facade: The service facade.
        template: The template path (file or directory).
        data: Optional data file path.
        format_name: Optional format name.
        dpi: Optional render DPI override.
        on_result: Callback invoked with every :class:`PreviewResult` (initial and each change).
        stop_event: Optional event that stops the loop when set (test/Ctrl-C seam).
        max_iterations: Optional bound on the number of change-driven re-renders (test seam).
    """
    from watchfiles import watch

    on_result(
        facade.render_preview(template, data, format_name, dpi=dpi, changed_file="(initial)")
    )
    if stop_event is not None and stop_event.is_set():
        return

    iterations = 0
    for changes in watch(
        *watch_paths(template, data),
        stop_event=stop_event,
        debounce=_DEBOUNCE_MS,
        rust_timeout=0,
    ):
        changed = _first_changed(changes)
        on_result(
            facade.render_preview(template, data, format_name, dpi=dpi, changed_file=changed)
        )
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return


def _first_changed(changes: set[tuple[object, str]]) -> str:
    """Return one representative changed path from a watchfiles change batch."""
    paths = sorted(path for _change, path in changes)
    return paths[0] if paths else "(unknown)"

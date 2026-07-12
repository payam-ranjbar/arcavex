"""Preview tests: stable path, keep-last-good on error, and the watch loop seam."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from arcavex.bootstrap import build_facade
from arcavex.clients.watch import run_watch

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELLO = _REPO_ROOT / "examples" / "hello-poster"


def _make_template(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the hello poster into a scratch dir and return (template, data)."""
    shutil.copy(_HELLO / "template.yaml", tmp_path / "template.yaml")
    shutil.copy(_HELLO / "logo.png", tmp_path / "logo.png")
    data = tmp_path / "data.yaml"
    data.write_text("title: One\nsubtitle: first\n", encoding="utf-8")
    return tmp_path / "template.yaml", data


def test_preview_path_is_stable(tmp_path: Path) -> None:
    facade = build_facade()
    template, data = _make_template(tmp_path)
    a = facade.render_preview(template, data, "square")
    b = facade.render_preview(template, data, "square")
    assert a.ok and b.ok
    assert a.output_path == b.output_path
    assert a.compile_ms is not None and a.render_ms is not None


def test_preview_reports_timings_under_two_seconds(tmp_path: Path) -> None:
    facade = build_facade()
    template, data = _make_template(tmp_path)
    result = facade.render_preview(template, data, "square")
    assert result.ok
    # Spec §6.1.1 loop latency target: well under two seconds on this reference machine.
    assert (result.compile_ms or 0) + (result.render_ms or 0) < 2000.0


def test_preview_keeps_last_good_on_error(tmp_path: Path) -> None:
    facade = build_facade()
    template, data = _make_template(tmp_path)
    good = facade.render_preview(template, data, "square")
    assert good.ok
    good_bytes = Path(good.output_path).read_bytes()

    # Seed a compile error: reference an undefined variable.
    template.write_text(
        """
version: 0.1.0
formats: {square: {canvas: {width: 100px, height: 100px, dpi: 96}}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "{{ undefined_var }}"
      style: {font: Inter, font_size: 10px, color: white}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
""",
        encoding="utf-8",
    )
    bad = facade.render_preview(template, data, "square", changed_file=str(template))
    assert not bad.ok
    assert any(d.is_error() and d.source is not None for d in bad.diagnostics)
    # The last good preview file is left byte-for-byte intact.
    assert Path(good.output_path).read_bytes() == good_bytes


def test_watch_rerenders_on_data_change(tmp_path: Path) -> None:
    """Drive the watch loop through its stop-event seam and observe a re-render."""
    facade = build_facade()
    template, data = _make_template(tmp_path)
    results: list = []
    stop = threading.Event()

    thread = threading.Thread(
        target=run_watch,
        args=(facade, template, data, "square", None, results.append),
        kwargs={"stop_event": stop, "max_iterations": 1},
        daemon=True,
    )
    thread.start()
    try:
        _wait_until(lambda: len(results) >= 1, timeout=15.0)
        assert results[0].ok  # initial render
        good_bytes = Path(results[0].output_path).read_bytes()

        # Re-touch the data until the change-driven render lands (watcher startup race).
        deadline = time.time() + 20.0
        n = 1
        while len(results) < 2 and time.time() < deadline:
            data.write_text(f"title: Changed {n}\nsubtitle: v{n}\n", encoding="utf-8")
            n += 1
            time.sleep(0.4)
        assert len(results) >= 2, "watch did not re-render on the data change"
        assert results[-1].ok
        assert results[-1].changed_file is not None
        # The re-render produced fresh bytes to the same stable path.
        assert Path(results[-1].output_path).read_bytes() != good_bytes
    finally:
        stop.set()
        thread.join(timeout=10.0)


def _wait_until(predicate, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met within timeout")

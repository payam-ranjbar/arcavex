"""Preview tests: stable path, keep-last-good on error, and the watch loop seam."""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
from pathlib import Path

from arcavex.bootstrap import build_facade
from arcavex.clients.watch import run_watch

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELLO = _REPO_ROOT / "tests" / "fixtures" / "basic-poster"


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


def test_preview_path_folds_every_pixel_changing_input(tmp_path: Path) -> None:
    """Two variants of one template previewed side by side must land in two files.

    The stable path used to key on the template alone, so ``--data b.yaml`` silently overwrote
    the ``--data a.yaml`` preview a person was still looking at, and the file flipped between the
    two. Every input that changes the pixels now takes part in the name, the same inputs always
    give the same path (``--watch`` and the desktop re-read one file across renders), and the
    plain template + format case keeps its historical path so existing viewers stay pointed at
    the same file.
    """
    facade = build_facade()
    template, data = _make_template(tmp_path)
    other = tmp_path / "other.yaml"
    other.write_text("title: Two\nsubtitle: second\n", encoding="utf-8")

    plain = facade.preview_path(template, "square")
    historical_key = hashlib.sha256(str(template.resolve()).encode("utf-8")).hexdigest()[:16]
    assert plain.name == f"{historical_key}.square.png"

    full = dict(data=data, locale="fa", dpi=96, style="paper@1.0.0")
    assert facade.preview_path(template, "square", **full) == facade.preview_path(
        template, "square", **full
    )
    # The directory and file spellings of a template still agree, variant or not (CR-4).
    assert facade.preview_path(tmp_path, "square", data=data) == facade.preview_path(
        template, "square", data=data
    )

    variants = [
        plain,
        facade.preview_path(template, "square", data=data),
        facade.preview_path(template, "square", data=other),
        facade.preview_path(template, "square", data=data, locale="fa"),
        facade.preview_path(template, "square", data=data, dpi=72),
        facade.preview_path(template, "square", data=data, style="./style.yaml"),
    ]
    assert len(set(variants)) == len(variants), variants
    assert all(v.parent == plain.parent for v in variants)


def test_two_data_variants_preview_to_two_files(tmp_path: Path) -> None:
    facade = build_facade()
    template, data = _make_template(tmp_path)
    other = tmp_path / "other.yaml"
    other.write_text("title: Two\nsubtitle: second\n", encoding="utf-8")
    a = facade.render_preview(template, data, "square")
    b = facade.render_preview(template, other, "square")
    assert a.ok and b.ok
    assert a.output_path != b.output_path
    assert Path(a.output_path).is_file() and Path(b.output_path).is_file()
    assert a.content_sha256 != b.content_sha256
    # A re-render of the first variant lands back on its own file, untouched by the second.
    again = facade.render_preview(template, data, "square")
    assert again.output_path == a.output_path


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


def test_watch_rerenders_on_single_save(tmp_path: Path) -> None:
    """CR-7: one save re-renders — no retry loop, because the watcher is live before the
    initial render, so the startup race that used to drop that save is gone."""
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
        assert results[0].ok  # initial render; watcher already registered
        good_bytes = Path(results[0].output_path).read_bytes()

        # A single save (not a retry loop) must produce exactly one re-render.
        time.sleep(0.3)  # settle so the write clearly follows the initial render
        data.write_text("title: Changed\nsubtitle: v2\n", encoding="utf-8")
        _wait_until(lambda: len(results) >= 2, timeout=15.0)
        assert results[-1].ok
        assert results[-1].changed_file is not None
        # The re-render produced fresh bytes to the same stable path.
        assert Path(results[-1].output_path).read_bytes() != good_bytes
    finally:
        stop.set()
        thread.join(timeout=10.0)
        assert not thread.is_alive()


def test_watch_stops_promptly_without_events(tmp_path: Path) -> None:
    """CR-13: a set stop_event is honored within the finite rust timeout, without needing a
    filesystem event to wake the loop, so the thread never leaks."""
    facade = build_facade()
    template, data = _make_template(tmp_path)
    results: list = []
    stop = threading.Event()

    thread = threading.Thread(
        target=run_watch,
        args=(facade, template, data, "square", None, results.append),
        kwargs={"stop_event": stop},
        daemon=True,
    )
    thread.start()
    _wait_until(lambda: len(results) >= 1, timeout=15.0)  # initial render
    stop.set()
    thread.join(timeout=5.0)
    assert not thread.is_alive()


def _wait_until(predicate, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met within timeout")

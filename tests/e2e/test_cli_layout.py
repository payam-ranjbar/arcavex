"""CLI transcript tests for the Phase 2 flags: layout inspect, render --debug, exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_IPEN = _REPO / "examples" / "ipen-bilingual"
_TEMPLATE = _IPEN / "template.yaml"
_DATA = _IPEN / "data.yaml"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def test_layout_inspect_json() -> None:
    proc = _run(
        ["layout", "inspect", str(_TEMPLATE), "--data", str(_DATA),
         "--format", "square", "--locale", "fa", "--json"]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["response_version"] >= 1
    assert payload["canvas_px"] == [1080, 1080]
    assert payload["root"]["id"] == "root"


def test_layout_inspect_human_shows_anchors() -> None:
    proc = _run(
        ["layout", "inspect", str(_TEMPLATE), "--data", str(_DATA), "--format", "square"]
    )
    assert proc.returncode == 0, proc.stderr
    assert "canvas" in proc.stdout and "coverage" in proc.stdout


def test_render_debug_flag(tmp_path: Path) -> None:
    out = tmp_path / "dbg.png"
    proc = _run(
        ["render", str(_TEMPLATE), "--data", str(_DATA), "--format", "square",
         "--locale", "en", "-o", str(out), "--debug"]
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file() and out.stat().st_size > 0


def test_render_all_six_targets(tmp_path: Path) -> None:
    for fmt in ("square", "story", "a4"):
        for locale in ("en", "fa"):
            out = tmp_path / f"{locale}-{fmt}.png"
            proc = _run(
                ["render", str(_TEMPLATE), "--data", str(_DATA), "--format", fmt,
                 "--locale", locale, "-o", str(out), "--quiet"]
            )
            assert proc.returncode == 0, f"{fmt}/{locale}: {proc.stderr}"
            assert out.is_file()


def _seeded(tmp_path: Path, body: str) -> Path:
    template = tmp_path / "t.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {square: {canvas: {width: 200px, height: 200px, dpi: 72}}}\n"
        "root:\n  type: group\n  id: root\n  children:\n" + body,
        encoding="utf-8",
    )
    return template


def test_missing_font_exit_3(tmp_path: Path) -> None:
    template = _seeded(
        tmp_path,
        "    - id: t\n      type: text\n      text: hi\n"
        "      style: {font: Nonesuch, font_size: 20pt, color: black}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left},"
        " size: {w: fill, h: fit_content}}\n",
    )
    proc = _run(["render", str(template), "--format", "square", "-o", str(tmp_path / "o.png")])
    assert proc.returncode == 3  # missing dependency/font


def test_constraint_cycle_exit_1(tmp_path: Path) -> None:
    template = _seeded(
        tmp_path,
        "    - id: n1\n      type: shape\n      shape: rect\n"
        "      constraints: {anchor: {top: n2.bottom, left: parent.left},"
        " size: {w: 5pt, h: 5pt}}\n"
        "    - id: n2\n      type: shape\n      shape: rect\n"
        "      constraints: {anchor: {top: n1.bottom, left: parent.left},"
        " size: {w: 5pt, h: 5pt}}\n",
    )
    proc = _run(["render", str(template), "--format", "square", "-o", str(tmp_path / "o.png")])
    assert proc.returncode == 1
    assert "ARC-LAY-052" in proc.stderr

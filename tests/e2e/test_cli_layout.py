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


def _overlap_template(tmp_path: Path) -> Path:
    """A shadowed strip spilling over a clean neighbour, plus a genuine 4pt text collision."""
    template = tmp_path / "overlaps.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {sq: {canvas: {width: 400px, height: 400px, dpi: 72}}}\n"
        "root:\n  type: group\n  id: root\n  children:\n"
        "    - id: strip\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#3366cc'}\n"
        "      effects:\n"
        "        - {name: drop-shadow, params: "
        "{dx: 0pt, dy: 0pt, blur: 20pt, color: '#000000'}}\n"
        "      constraints: {anchor: {top: parent.top+20pt, left: parent.left+20pt}, "
        "size: {w: 100pt, h: 40pt}}\n"
        "    - id: tag\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#cc3366'}\n"
        "      constraints: {anchor: {top: parent.top+20pt, left: strip.right+10pt}, "
        "size: {w: 100pt, h: 40pt}}\n"
        "    - id: venue-1\n      type: text\n      text: First venue line\n"
        "      style: {font: Inter, font_size: 14pt, color: '#000000'}\n"
        "      constraints: {anchor: {top: parent.top+200pt, left: parent.left+20pt}, "
        "size: {w: 200pt, h: 40pt}}\n"
        "    - id: venue-2\n      type: text\n      text: Second venue line\n"
        "      style: {font: Inter, font_size: 14pt, color: '#000000'}\n"
        "      constraints: {anchor: {top: venue-1.bottom-4pt, left: parent.left+20pt}, "
        "size: {w: 200pt, h: 40pt}}\n",
        encoding="utf-8",
    )
    return template


def test_layout_inspect_human_prints_both_bounds_and_paint_bounds(tmp_path: Path) -> None:
    # P2-1: the inflated box must be visible per node, or a halo overlap's rect is unexplainable.
    proc = _run(
        ["layout", "inspect", str(_overlap_template(tmp_path)), "--format", "sq", "--no-color"]
    )
    assert proc.returncode == 0, proc.stderr
    # The shadowed strip's paint box is 60pt (3 sigma) larger on every side than its layout box.
    assert "strip shape bounds (20.0, 20.0, 100.0, 40.0)pt" in proc.stdout
    assert "paint (-40.0, -40.0, 220.0, 160.0)pt" in proc.stdout
    # Both boxes are printed for every node, including the ones the effects never touched.
    assert "tag shape bounds (130.0, 20.0, 100.0, 40.0)pt" in proc.stdout
    assert "paint (130.0, 20.0, 100.0, 40.0)pt" in proc.stdout
    # No line may wrap, or a rect gets split mid-number and stops being machine-readable.
    assert max(len(line) for line in proc.stdout.splitlines()) <= 100


def test_layout_inspect_human_demotes_halo_below_content(tmp_path: Path) -> None:
    # P2-1: the genuine collision gets the heading; the shadow spill is a subordinate section.
    proc = _run(
        ["layout", "inspect", str(_overlap_template(tmp_path)), "--format", "sq", "--no-color"]
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "overlaps: 1 content, 1 effect spill" in out
    assert "effect spill (paint bounds only" in out
    # The content collision is listed above the spill subheading, not buried among it.
    assert out.index("venue-1 ∩ venue-2") < out.index("effect spill (paint bounds only")


def test_layout_inspect_json_carries_overlap_kind(tmp_path: Path) -> None:
    # P2-1: an agent filters on `kind` rather than re-deriving it from the geometry.
    proc = _run(
        ["layout", "inspect", str(_overlap_template(tmp_path)), "--format", "sq", "--json"]
    )
    assert proc.returncode == 0, proc.stderr
    overlaps = json.loads(proc.stdout)["overlaps"]
    by_pair = {frozenset((o["a"], o["b"])): o["kind"] for o in overlaps}
    assert by_pair == {
        frozenset(("strip", "tag")): "halo",
        frozenset(("venue-1", "venue-2")): "content",
    }


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

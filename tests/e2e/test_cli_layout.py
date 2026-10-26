"""CLI transcript tests for the Phase 2 flags: layout inspect, render --debug, exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_IPEN = _REPO / "tests" / "fixtures" / "bilingual-poster"
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
    # The inflated box must be visible per node, or a halo overlap's rect cannot be checked.
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
    # The content collision gets the heading; the shadow spill is a subordinate section.
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
    # A caller filters on `kind` rather than re-deriving it from the geometry.
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


def _cross_group_template(tmp_path: Path) -> Path:
    """A full-bleed backdrop plus two leaves in different groups that genuinely collide."""
    template = tmp_path / "cross-group.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {sq: {canvas: {width: 400pt, height: 400pt, dpi: 72}}}\n"
        "root:\n  type: group\n  id: root\n  children:\n"
        "    - id: bg\n      type: shape\n      shape: rect\n"
        "      style: {fill: '#eeeeee'}\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: 400pt, h: 400pt}}\n"
        "    - id: left-group\n      type: group\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: 100pt, h: 100pt}}\n"
        "      children:\n"
        "        - id: a\n          type: shape\n          shape: rect\n"
        "          style: {fill: '#3366cc'}\n"
        "          constraints: {anchor: {top: parent.top, left: parent.left+50pt}, "
        "size: {w: 100pt, h: 100pt}}\n"
        "    - id: right-group\n      type: group\n"
        "      constraints: {anchor: {top: parent.top, left: parent.left+100pt}, "
        "size: {w: 100pt, h: 100pt}}\n"
        "      children:\n"
        "        - id: b\n          type: shape\n          shape: rect\n"
        "          style: {fill: '#cc3366'}\n"
        "          constraints: {anchor: {top: parent.top, left: parent.left-100pt}, "
        "size: {w: 100pt, h: 100pt}}\n",
        encoding="utf-8",
    )
    return template


def _overflow_template(tmp_path: Path) -> Path:
    """A text node that fits cleanly beside one clipped by a tiny fixed box + wrap/clip."""
    template = tmp_path / "overflow.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {sq: {canvas: {width: 400px, height: 400px, dpi: 72}}}\n"
        "root:\n  type: group\n  id: root\n  children:\n"
        "    - id: clean\n      type: text\n      text: Fits\n"
        "      style: {font: Inter, font_size: 14pt, color: '#000000'}\n"
        "      constraints: {anchor: {top: parent.top+20pt, left: parent.left+20pt}, "
        "size: {w: 200pt, h: 40pt}}\n"
        "    - id: bad\n      type: text\n"
        "      text: This is far too much text to fit in a tiny fixed box at this size\n"
        "      style: {font: Inter, font_size: 40pt, color: '#000000'}\n"
        "      fit: {policy: wrap, overflow: clip}\n"
        "      constraints: {anchor: {top: parent.top+100pt, left: parent.left+20pt}, "
        "size: {w: 80pt, h: 40pt}}\n",
        encoding="utf-8",
    )
    return template


def _node_ids(node: dict) -> list[str]:
    ids = [node["id"]]
    for child in node["children"]:
        ids.extend(_node_ids(child))
    return ids


def test_layout_inspect_help_lists_inspection_flags() -> None:
    proc = _run(["layout", "inspect", "--help"])
    assert proc.returncode == 0, proc.stderr
    for flag in ("--text-only", "--overflow-only", "--cross-group"):
        assert flag in proc.stdout


def test_layout_inspect_text_only_hides_non_text_nodes_and_overlaps(tmp_path: Path) -> None:
    proc = _run(
        ["layout", "inspect", str(_overlap_template(tmp_path)), "--format", "sq",
         "--text-only", "--no-color"]
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "venue-1" in out and "venue-2" in out
    assert "strip shape bounds" not in out
    assert "tag shape bounds" not in out
    assert "strip ∩ tag" not in out
    assert "venue-1 ∩ venue-2" in out


def test_layout_inspect_text_only_json_filters_tree_and_overlaps(tmp_path: Path) -> None:
    proc = _run(
        ["layout", "inspect", str(_overlap_template(tmp_path)), "--format", "sq",
         "--text-only", "--json"]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)

    def kinds(node: dict) -> list[str]:
        out = [node["kind"]]
        for child in node["children"]:
            out.extend(kinds(child))
        return out

    assert "shape" not in kinds(payload["root"])
    assert "text" in kinds(payload["root"])
    assert {(o["a"], o["b"]) for o in payload["overlaps"]} == {("venue-1", "venue-2")}


def test_layout_inspect_overflow_only_keeps_only_overflowing_nodes(tmp_path: Path) -> None:
    template = _overflow_template(tmp_path)
    proc = _run(
        ["layout", "inspect", str(template), "--format", "sq", "--overflow-only", "--json"]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "bad" in _node_ids(payload["root"])
    assert "clean" not in _node_ids(payload["root"])

    def overflow_kinds(node: dict) -> dict[str, str]:
        out = {node["id"]: (node["overflow"] or {}).get("kind", "none")}
        for child in node["children"]:
            out.update(overflow_kinds(child))
        return out

    assert overflow_kinds(payload["root"])["bad"] == "clipped"

    human = _run(
        ["layout", "inspect", str(template), "--format", "sq", "--overflow-only", "--no-color"]
    )
    assert human.returncode == 0, human.stderr
    assert "overflow" in human.stdout
    assert "clean" not in human.stdout


def test_layout_inspect_cross_group_opt_in(tmp_path: Path) -> None:
    template = _cross_group_template(tmp_path)
    default = _run(["layout", "inspect", str(template), "--format", "sq", "--json"])
    assert default.returncode == 0, default.stderr
    payload = json.loads(default.stdout)
    assert payload["overlaps"] == []
    assert payload["cross_group_overlaps"] == []

    proc = _run(
        ["layout", "inspect", str(template), "--format", "sq", "--cross-group", "--json"]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["overlaps"] == []
    assert {(o["a"], o["b"]) for o in payload["cross_group_overlaps"]} == {("a", "b")}

    human = _run(
        ["layout", "inspect", str(template), "--format", "sq", "--cross-group", "--no-color"]
    )
    assert human.returncode == 0, human.stderr
    assert "cross-group overlaps" in human.stdout


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

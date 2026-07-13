"""Layout JSON bounds snapshots for the IPEN bilingual example (spec §8.5).

These are cheap, cross-platform-deterministic geometry snapshots: for each (format, locale)
target the resolved per-node bounds (in points) are serialized and compared to a stored JSON
file. They catch layout regressions without pixel comparison.

Update mechanism: run with ``ARCAVEX_UPDATE_SNAPSHOTS=1`` to (re)write the ``.json`` files,
then review the diff before committing::

    ARCAVEX_UPDATE_SNAPSHOTS=1 .venv/Scripts/python.exe -m pytest tests/layout_snapshots -q
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import LayoutNodeReport

_REPO = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO / "examples" / "ipen-bilingual" / "template.yaml"
_DATA = _REPO / "examples" / "ipen-bilingual" / "data.yaml"
_SNAP_DIR = Path(__file__).parent / "ipen"

_TARGETS = [
    ("square", "en"),
    ("square", "fa"),
    ("story", "en"),
    ("story", "fa"),
    ("a4", "en"),
    ("a4", "fa"),
]


def _node_bounds(node: LayoutNodeReport) -> dict[str, object]:
    return {
        "id": node.id,
        "kind": node.kind,
        "bounds_pt": [round(v, 3) for v in node.bounds_pt],
        "rotate_deg": node.rotate_deg,
        "overflow": node.overflow.kind if node.overflow else "none",
        "children": [_node_bounds(c) for c in node.children],
    }


def _snapshot(fmt: str, locale: str) -> dict[str, object]:
    facade = build_facade()
    report = facade.inspect_layout(_TEMPLATE, _DATA, fmt, locale)
    assert report.ok, report.diagnostics
    assert report.root is not None
    return {
        "format": fmt,
        "locale": locale,
        "canvas_pt": [round(v, 3) for v in report.canvas_pt],
        "root": _node_bounds(report.root),
    }


@pytest.mark.parametrize(("fmt", "locale"), _TARGETS)
def test_ipen_layout_snapshot(fmt: str, locale: str) -> None:
    snapshot = _snapshot(fmt, locale)
    path = _SNAP_DIR / f"{fmt}-{locale}.json"
    serialized = json.dumps(snapshot, indent=2, ensure_ascii=False)
    if os.environ.get("ARCAVEX_UPDATE_SNAPSHOTS") == "1":
        _SNAP_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized + "\n", encoding="utf-8")
        return
    assert path.is_file(), f"missing snapshot {path.name}; run with ARCAVEX_UPDATE_SNAPSHOTS=1"
    assert path.read_text(encoding="utf-8") == serialized + "\n"

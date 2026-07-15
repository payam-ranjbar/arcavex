"""End-to-end CLI tests for exporter selection, options, and the budget exit code."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO_TEMPLATE = _REPO_ROOT / "examples" / "hello-poster" / "template.yaml"
HELLO_DATA = _REPO_ROOT / "examples" / "hello-poster" / "data.yaml"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=None if cwd is None else str(cwd),
    )


def _render(out: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    args = [
        "render", str(HELLO_TEMPLATE), "--data", str(HELLO_DATA),
        "--format", "square", "-o", str(out),
    ]
    return _run(args + (extra or []))


def test_extension_selects_jpeg(tmp_path: Path) -> None:
    out = tmp_path / "poster.jpg"
    proc = _render(out, ["--quality", "80"])
    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes()[:2] == b"\xff\xd8"


def test_extension_selects_webp_lossless(tmp_path: Path) -> None:
    out = tmp_path / "poster.webp"
    proc = _render(out, ["--lossless"])
    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes()[:4] == b"RIFF"


def test_extension_selects_pdf(tmp_path: Path) -> None:
    out = tmp_path / "poster.pdf"
    proc = _render(out)
    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes()[:5] == b"%PDF-"


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    out = tmp_path / "poster.tiff"
    proc = _render(out)
    assert proc.returncode == 1  # EXIT_VALIDATION, not a crash
    assert "ARC-EXP-011" in proc.stderr
    assert not out.exists()


def test_oversized_render_exits_with_budget_code(tmp_path: Path) -> None:
    template = tmp_path / "huge.yaml"
    template.write_text(
        "version: 0.1.0\n"
        "formats: {huge: {canvas: {width: 40000px, height: 40000px, dpi: 72}}}\n"
        "root: {type: group, id: root, children: ["
        "{id: bg, type: shape, shape: rect, style: {fill: '#123456'}, "
        "constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}}]}\n",
        encoding="utf-8",
    )
    out = tmp_path / "huge.png"
    proc = _run(["render", str(template), "--format", "huge", "-o", str(out)])
    assert proc.returncode == 4  # EXIT_BUDGET
    assert "ARC-RND-020" in proc.stderr
    assert not out.exists()

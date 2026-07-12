"""End-to-end CLI tests via subprocess: rendering, determinism, and exit codes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO_TEMPLATE = _REPO_ROOT / "examples" / "hello-poster" / "template.yaml"
HELLO_DATA = _REPO_ROOT / "examples" / "hello-poster" / "data.yaml"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_render_hello_poster(tmp_path: Path) -> None:
    out = tmp_path / "hello.png"
    proc = _run(
        [
            "render",
            str(HELLO_TEMPLATE),
            "--data",
            str(HELLO_DATA),
            "--format",
            "square",
            "-o",
            str(out),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
    data = out.read_bytes()
    assert data[:8] == PNG_SIGNATURE
    assert len(data) > 10_000


def test_render_is_deterministic(tmp_path: Path) -> None:
    hashes = []
    for name in ("a.png", "b.png"):
        out = tmp_path / name
        proc = _run(
            [
                "render",
                str(HELLO_TEMPLATE),
                "--data",
                str(HELLO_DATA),
                "--format",
                "square",
                "-o",
                str(out),
            ]
        )
        assert proc.returncode == 0, proc.stderr
        hashes.append(hashlib.sha256(out.read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]


def test_validate_ok_json() -> None:
    proc = _run(
        [
            "validate",
            str(HELLO_TEMPLATE),
            "--data",
            str(HELLO_DATA),
            "--json",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True


def test_failing_template_exit_and_located_json(tmp_path: Path) -> None:
    template = tmp_path / "req.yaml"
    template.write_text(
        """
version: 0.1.0
variables:
  speaker: {type: string, required: true}
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "{{ speaker }}"
      style: {font: Inter, font_size: 20px, color: white}
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 80%, h: fit_content}
""",
        encoding="utf-8",
    )
    data = tmp_path / "data.yaml"
    data.write_text("other: 1\n", encoding="utf-8")
    proc = _run(
        [
            "validate",
            str(template),
            "--data",
            str(data),
            "--format",
            "square",
            "--json",
        ]
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["response_version"] == 1
    assert payload["ok"] is False
    diag = payload["diagnostics"][0]
    assert diag["code"] == "ARC-TPL-014"
    # File and line must come from the same source: the template's variable declaration,
    # not the data file (which has no line for a variable it omits). See CR-6.
    assert diag["source"]["file"] == str(template)
    assert diag["source"]["keypath"] == "speaker"
    assert diag["source"]["line"] is not None
    assert diag["hint"]


def test_missing_template_file_exit_3(tmp_path: Path) -> None:
    proc = _run(
        ["render", str(tmp_path / "nope.yaml"), "--format", "square", "-o", str(tmp_path / "o.png")]
    )
    assert proc.returncode == 3

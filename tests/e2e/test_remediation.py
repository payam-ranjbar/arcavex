"""End-to-end CLI remediation tests: exit codes, default output, inference, visibility.

These guard the Phase 0 exit criterion that failing inputs produce located diagnostics and
correct exit codes (0/1/3/4/5), and the §6.3 reporting behaviors (default output naming and
inference reporting).
"""

from __future__ import annotations

import json
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
        cwd=str(cwd) if cwd is not None else None,
    )


def _template(tmp_path: Path, body: str, name: str = "t.yaml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_asset_exit_3(tmp_path: Path) -> None:
    template = _template(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: pic
      type: image
      asset: nope.png
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 50px, h: 50px}
""",
    )
    proc = _run(
        ["render", str(template), "--format", "square", "-o", str(tmp_path / "o.png"), "--json"]
    )
    assert proc.returncode == 3, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["diagnostics"][0]["code"] == "ARC-AST-001"


def test_budget_exit_4(tmp_path: Path) -> None:
    expr = "{{ " + "1" + " + 1" * 5000 + " }}"
    template = _template(
        tmp_path,
        "version: 0.1.0\n"
        "formats:\n  square: {canvas: {width: 100px, height: 100px, dpi: 96}}\n"
        "root:\n"
        "  type: group\n"
        "  id: root\n"
        "  children:\n"
        "    - id: t\n"
        "      type: text\n"
        f"      text: \"{expr}\"\n"
        "      style: {font_size: 10px}\n"
        "      constraints:\n"
        "        anchor: {top: parent.top, left: parent.left}\n"
        "        size: {w: fill, h: fit_content}\n",
    )
    proc = _run(["validate", str(template), "--format", "square", "--json"])
    assert proc.returncode == 4, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["diagnostics"][0]["code"] == "ARC-TPL-062"


def test_unknown_font_exit_3(tmp_path: Path) -> None:
    template = _template(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "hi"
      style: {font: NoSuchFamily, font_size: 10px, color: white}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
""",
    )
    proc = _run(["validate", str(template), "--format", "square", "--json"])
    assert proc.returncode == 3, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["diagnostics"][0]["code"] == "ARC-RND-010"


def test_default_output_name_and_reported(tmp_path: Path) -> None:
    """DX-6: no -o produces '<stem>.<format>.png' in the CWD and reports it."""
    template = _template(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 60px, height: 60px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: bg
      type: shape
      shape: rect
      style: {fill: "#102030"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
""",
    )
    proc = _run(["render", str(template), "--format", "square", "--json"], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["inferred"]["output"] == "t.square.png"
    assert (tmp_path / "t.square.png").is_file()
    assert payload["output_path"].endswith("t.square.png")


def test_inference_reported_in_json(tmp_path: Path) -> None:
    """DX-7: inferred format and preview_data fallback are reported."""
    template = _template(
        tmp_path,
        """
version: 0.1.0
variables:
  title: {type: string, required: true}
formats:
  square: {canvas: {width: 60px, height: 60px, dpi: 96}}
preview_data:
  title: "Preview"
root:
  type: group
  id: root
  children:
    - id: t
      type: text
      text: "{{ title }}"
      style: {font: Inter, font_size: 10px, color: white}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
""",
    )
    proc = _run(["render", str(template), "--json"], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["inferred"]["format"] == "square"
    assert payload["inferred"]["data"] == "preview_data"


def test_visible_false_not_painted(tmp_path: Path) -> None:
    """CR-2: a full-canvas 'visible: false' rect leaves the canvas transparent."""
    from PIL import Image

    template = _template(
        tmp_path,
        """
version: 0.1.0
formats:
  square: {canvas: {width: 40px, height: 40px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: red
      type: shape
      shape: rect
      visible: false
      style: {fill: "#ff0000"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
""",
    )
    out = tmp_path / "hidden.png"
    proc = _run(["render", str(template), "--format", "square", "-o", str(out)])
    assert proc.returncode == 0, proc.stderr
    im = Image.open(out).convert("RGBA")
    # The hidden red rect must not paint: the center pixel stays fully transparent.
    assert im.getpixel((im.width // 2, im.height // 2)) == (0, 0, 0, 0)


def test_response_version_present(tmp_path: Path) -> None:
    proc = _run(["validate", str(HELLO_TEMPLATE), "--data", str(HELLO_DATA), "--json"])
    payload = json.loads(proc.stdout)
    assert payload["response_version"] == 1

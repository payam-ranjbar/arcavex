"""E2E: ARC-LAY-058 surfaces a converged shrink and --strict makes it fatal (A3).

The same 54pt headline is declared for both formats. In 'narrow' (240px = 180pt at 96dpi) the
text cannot fit at 54pt and 'shrink_to_fit' converges smaller; in 'wide' (1200px = 900pt) it
fits. Validation reports the warning for 'narrow' only, and --strict turns it into a failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# 240px at 96dpi = 180pt; 'Shrink me' at 54pt is wider than that and must shrink. max_lines: 1
# makes the width the binding constraint (height is fit_content), so the search converges.
TEMPLATE = """\
version: 0.1.0
formats:
  narrow: {canvas: {width: 240px, height: 240px, dpi: 96}}
  wide: {canvas: {width: 1200px, height: 240px, dpi: 96}}
root:
  type: group
  id: root
  children:
    - id: title
      type: text
      text: "Shrink me"
      style: {font: Inter, font_size: 54pt, color: "#000000"}
      fit: {policy: shrink_to_fit, min_size: 10pt, max_lines: 1}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: 100%, h: fit_content}
"""


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "shrink.yaml"
    path.write_text(TEMPLATE, encoding="utf-8")
    return path


def test_validate_reports_shrink_warning_for_one_format_json(tmp_path: Path) -> None:
    template = _write(tmp_path)
    proc = _run(["validate", str(template), "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    warnings = [d for d in payload["diagnostics"] if d["code"] == "ARC-LAY-058"]
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["severity"] == "warning"
    assert "'title'" in warning["message"]
    assert "'narrow'" in warning["message"]
    assert "54.0pt" in warning["message"]
    assert "'wide'" not in warning["message"]


def test_validate_strict_promotes_shrink_warning_to_error(tmp_path: Path) -> None:
    template = _write(tmp_path)
    proc = _run(["validate", str(template), "--json", "--strict"])
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    warning = next(d for d in payload["diagnostics"] if d["code"] == "ARC-LAY-058")
    assert warning["severity"] == "error"


def test_render_strict_exits_nonzero_on_shrink(tmp_path: Path) -> None:
    template = _write(tmp_path)
    out = tmp_path / "out.png"
    proc = _run(
        ["render", str(template), "--format", "narrow", "-o", str(out), "--json", "--strict"]
    )
    assert proc.returncode == 1, proc.stderr
    assert out.is_file()
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False


def test_render_without_strict_succeeds_with_warning(tmp_path: Path) -> None:
    """The default render is correct and non-fatal; --strict is what makes the warning fatal."""
    template = _write(tmp_path)
    out = tmp_path / "out.png"
    proc = _run(["render", str(template), "--format", "narrow", "-o", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert any(d["code"] == "ARC-LAY-058" for d in payload["diagnostics"])

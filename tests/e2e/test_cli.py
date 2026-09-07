"""End-to-end CLI tests via subprocess: rendering, determinism, and exit codes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO_TEMPLATE = _REPO_ROOT / "tests" / "fixtures" / "basic-poster" / "template.yaml"
HELLO_DATA = _REPO_ROOT / "tests" / "fixtures" / "basic-poster" / "data.yaml"
POPART_TEMPLATE = _REPO_ROOT / "tests" / "fixtures" / "basic-poster" / "template.yaml"
POPART_DATA = _REPO_ROOT / "tests" / "fixtures" / "basic-poster" / "data.yaml"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=None if cwd is None else str(cwd),
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


def test_render_with_style_flag_name_version(tmp_path: Path) -> None:
    """CR-2/DX-2: --style name@version resolves a library pack on the CLI."""
    out = tmp_path / "styled.png"
    proc = _run(
        [
            "render", str(POPART_TEMPLATE),
            "--data", str(POPART_DATA),
            "--format", "square",
            "--style", "pop-art@0.1.0",
            "-o", str(out),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file() and out.read_bytes()[:8] == PNG_SIGNATURE


def test_render_with_style_flag_local_file(tmp_path: Path) -> None:
    """CR-2/DX-2: --style ./file.yaml resolves relative to the invocation directory."""
    out = tmp_path / "styled_file.png"
    proc = _run(
        [
            "render", str(POPART_TEMPLATE),
            "--data", str(POPART_DATA),
            "--format", "square",
            "--style", "./library-seed/styles/pop-art/0.1.0.yaml",
            "-o", str(out),
        ],
        cwd=_REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file() and out.read_bytes()[:8] == PNG_SIGNATURE


def test_effects_list_json() -> None:
    """DX-6: effects list --json emits a versioned catalog of effects and their params."""
    proc = _run(["effects", "list", "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["response_version"] == 1 and payload["ok"] is True
    names = {e["name"] for e in payload["effects"]}
    assert {"drop-shadow", "halftone", "posterize"} <= names
    halftone = next(e for e in payload["effects"] if e["name"] == "halftone")
    assert halftone["category"] == "raster"
    assert any(p["name"] == "pitch" and p["type"] == "length" for p in halftone["params"])


def test_effects_inspect_unknown_exits_nonzero() -> None:
    proc = _run(["effects", "inspect", "no-such-effect"])
    assert proc.returncode != 0
    assert "no-such-effect" in (proc.stdout + proc.stderr)


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


def test_render_json_output_path_is_absolute_and_human_line_stays_as_typed(
    tmp_path: Path,
) -> None:
    """`-o hello.png` is relative to wherever the command ran. The human line quotes it as typed
    (the quick start shows exactly that), but --json and the MCP result are read by an assistant
    that may have run the command from another directory, so there the path must be absolute."""
    args = [
        "render", str(HELLO_TEMPLATE), "--data", str(HELLO_DATA), "--format", "square",
        "-o", "hello.png",
    ]
    machine = _run([*args, "--json"], cwd=tmp_path)
    assert machine.returncode == 0, machine.stderr
    payload = json.loads(machine.stdout)
    assert payload["output_path"] == str((tmp_path / "hello.png").resolve())
    assert Path(payload["output_path"]).is_file()

    human = _run([*args, "--no-color"], cwd=tmp_path)
    assert human.returncode == 0, human.stderr
    assert "Rendered hello.png" in human.stderr

    # With no -o the default name is inferred; the human line still shows that name, not where
    # it resolved to, and the JSON still says where the file is.
    bare = _run([*args[:-2], "--no-color"], cwd=tmp_path)
    assert bare.returncode == 0, bare.stderr
    assert "inferred: output=basic-poster.square.png" in bare.stderr
    assert "Rendered basic-poster.square.png" in bare.stderr
    bare_json = _run([*args[:-2], "--json"], cwd=tmp_path)
    bare_payload = json.loads(bare_json.stdout)
    assert bare_payload["inferred"]["output"] == "basic-poster.square.png"
    assert bare_payload["output_path"] == str((tmp_path / "basic-poster.square.png").resolve())

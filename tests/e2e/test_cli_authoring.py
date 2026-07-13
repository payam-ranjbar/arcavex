"""CLI transcript tests for the Phase 1 authoring commands and their exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELLO = _REPO_ROOT / "examples" / "hello-poster"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "arcavex.clients.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd) if cwd is not None else None,
    )


# ------------------------------------------------------------------------- doctor
def test_doctor_json_shape() -> None:
    proc = _run(["doctor", "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["response_version"] == 1
    assert payload["engine_version"]
    names = {c["name"] for c in payload["checks"]}
    assert {"python", "skia", "icu", "fonts", "temp_dir"} <= names


# ------------------------------------------------------------------------ explain
def test_explain_known_code_exit_0() -> None:
    proc = _run(["explain", "ARC-TPL-014"])
    assert proc.returncode == 0, proc.stderr
    assert "ARC-TPL-014" in proc.stdout


def test_explain_unknown_code_exit_1_json() -> None:
    proc = _run(["explain", "ARC-ZZZ-999", "--json"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["found"] is False
    assert payload["message"]


# ------------------------------------------------------------------- template new
def test_template_new_then_render_then_split(tmp_path: Path) -> None:
    target = tmp_path / "my-card"
    new = _run(["template", "new", str(target), "--json"])
    assert new.returncode == 0, new.stderr
    new_payload = json.loads(new.stdout)
    assert new_payload["ok"] is True
    fmt = new_payload["format"]

    out = tmp_path / "card.png"
    render = _run(["render", str(target), "--format", fmt, "-o", str(out)])
    assert render.returncode == 0, render.stderr
    assert out.is_file()

    split = _run(["template", "split", str(target), "--json"])
    assert split.returncode == 0, split.stderr
    assert (target / "schema.yaml").is_file()

    # Splitting again refuses (exit 1) because the template is already split.
    again = _run(["template", "split", str(target)])
    assert again.returncode == 1


def test_template_new_refuses_existing(tmp_path: Path) -> None:
    target = tmp_path / "exists"
    target.mkdir()
    (target / "x.txt").write_text("y", encoding="utf-8")
    proc = _run(["template", "new", str(target)])
    assert proc.returncode == 1


# ---------------------------------------------------------------- template inspect
def test_template_inspect_json_golden() -> None:
    proc = _run(["template", "inspect", str(_HELLO), "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["response_version"] == 1
    assert payload["ok"] is True
    assert {v["name"] for v in payload["variables"]} == {"title", "subtitle"}
    assert {f["name"] for f in payload["formats"]} == {"square", "story"}
    assert "title" in {n["id"] for n in payload["nodes"]}
    fn_names = {f["name"] for f in payload["functions"]}
    assert "locale_digits" in fn_names
    # DX-3: functions carry signatures, not bare names.
    locale_fn = next(f for f in payload["functions"] if f["name"] == "locale_digits")
    assert "locale_digits(" in locale_fn["signature"]


# ------------------------------------------------------------------ template check
def test_template_check_ok() -> None:
    proc = _run(["template", "check", str(_HELLO), "--json"])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ok"] is True


# ----------------------------------------------------------------- locale (CR-2)
def test_render_undeclared_locale_is_error() -> None:
    """--locale is applied now; hello-poster declares no locales, so 'fa' is ARC-TPL-100."""
    proc = _run(
        ["render", str(_HELLO), "--format", "square", "--locale", "fa", "--json"]
    )
    assert proc.returncode == 1  # a validation-class error, not a usage error
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert any(d["code"] == "ARC-TPL-100" for d in payload["diagnostics"])


def test_preview_locale_flag_parses() -> None:
    """The spec §6.1.1 example `preview … --locale fa` must parse (not exit 2 usage)."""
    proc = _run(
        [
            "preview",
            str(_HELLO / "template.yaml"),
            "--format",
            "square",
            "--locale",
            "fa",
            "--json",
        ]
    )
    assert proc.returncode != 2  # not a usage error
    payload = json.loads(proc.stdout)
    assert any(d["code"] == "ARC-TPL-100" for d in payload["diagnostics"])


# ------------------------------------------------------------------------ doctor paths
def test_doctor_reports_paths_row() -> None:
    """DX-9: doctor states where Arcavex reads/writes (ARCAVEX_HOME + preview cache)."""
    proc = _run(["doctor", "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    paths = next(c for c in payload["checks"] if c["name"] == "paths")
    assert "home=" in paths["detail"] and "preview cache=" in paths["detail"]


# ------------------------------------------------------------------------ preview
def test_preview_one_shot(tmp_path: Path) -> None:
    proc = _run(
        [
            "preview",
            str(_HELLO / "template.yaml"),
            "--data",
            str(_HELLO / "data.yaml"),
            "--format",
            "square",
            "--json",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["output_path"].endswith(".png")
    assert payload["compile_ms"] is not None and payload["render_ms"] is not None

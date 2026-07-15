"""CLI parity transcripts for the Phase 5 authoring subcommands (CR-2).

The MCP authoring operations (patch_template, set_data, import_data, add_asset, annotate_asset)
must also be reachable from the CLI so the CLI stays complete (spec line 39). These drive the
Typer app in-process with an isolated ``$ARCAVEX_HOME`` and assert on exit codes and ``--json``.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcavex.clients.cli import app

runner = CliRunner()


@pytest.fixture()
def scaffolded(arcavex_home: Path, tmp_path: Path) -> Path:
    """Scaffold a self-contained template directory via the CLI and return it."""
    target = tmp_path / "card"
    result = runner.invoke(app, ["template", "new", str(target), "--json"])
    assert result.exit_code == 0, result.output
    return target


@pytest.fixture()
def project(scaffolded: Path, tmp_path: Path) -> Path:
    """A project pinning the scaffolded template by path."""
    proj = tmp_path / "proj"
    result = runner.invoke(
        app, ["project", "new", str(proj), "--template", str(scaffolded), "--json"]
    )
    assert result.exit_code == 0, result.output
    return proj


def _tiny_png(path: Path) -> Path:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


# --------------------------------------------------------------------------- template patch
def test_cli_template_patch_applies(scaffolded: Path) -> None:
    result = runner.invoke(
        app,
        ["template", "patch", str(scaffolded / "template.yaml"),
         "--set", "nodes.title.style.font_size", "--value", "90px", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] and payload["applied"] == 1
    assert "90px" in (scaffolded / "template.yaml").read_text(encoding="utf-8")


def test_cli_template_patch_typo_is_rejected(scaffolded: Path) -> None:
    before = (scaffolded / "template.yaml").read_text(encoding="utf-8")
    result = runner.invoke(
        app,
        ["template", "patch", str(scaffolded / "template.yaml"),
         "--set", "nodes.title.style.fontsize", "--value", "90px", "--json"],
    )
    assert result.exit_code == 1
    assert "ARC-TPL-051" in result.stdout
    assert (scaffolded / "template.yaml").read_text(encoding="utf-8") == before


# --------------------------------------------------------------------------- data set/import
def test_cli_data_set_and_typo_warning(project: Path) -> None:
    ok = runner.invoke(
        app, ["data", "set", "title", "From CLI", "--project", str(project), "--json"]
    )
    assert ok.exit_code == 0, ok.output
    assert not any(
        d["code"] == "ARC-TPL-112" for d in json.loads(ok.stdout)["diagnostics"]
    )

    typo = runner.invoke(
        app, ["data", "set", "titel", "oops", "--project", str(project), "--json"]
    )
    assert typo.exit_code == 0
    payload = json.loads(typo.stdout)
    assert payload["ok"]
    assert any(d["code"] == "ARC-TPL-112" for d in payload["diagnostics"])


def test_cli_data_import(project: Path) -> None:
    src = project.parent / "extra.yaml"
    src.write_text("subtitle: Imported via CLI\n", encoding="utf-8")
    result = runner.invoke(
        app, ["data", "import", str(src), "--project", str(project), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"]


# --------------------------------------------------------------------------- asset add/annotate
def test_cli_asset_add_and_annotate(project: Path, tmp_path: Path) -> None:
    png = _tiny_png(tmp_path / "logo.png")
    added = runner.invoke(
        app, ["asset", "add", str(png), "--project", str(project), "--json"]
    )
    assert added.exit_code == 0, added.output
    sha = json.loads(added.stdout)["asset"]["sha256"]

    annotated = runner.invoke(
        app, ["asset", "annotate", sha, "--set", "facing=left", "--json"]
    )
    assert annotated.exit_code == 0, annotated.output
    payload = json.loads(annotated.stdout)
    assert payload["ok"] and payload["asset"]["annotations"] == {"facing": "left"}

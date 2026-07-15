"""End-to-end extension workflow (spec §7 Phase 6 exit criterion).

Drives the Typer app in-process with an isolated ``$ARCAVEX_HOME`` through the full lifecycle —
scaffold → validate → test → add → enable → render a template that uses the extension's component
— proving a reviewed local effect extension can be used WITHOUT modifying Arcavex core. Also
exercises the seeded-failure paths (disallowed import, determinism lint) and the shipped reference
extension.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcavex.clients.cli import app

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE = REPO_ROOT / "examples" / "extensions" / "paper-texture"
runner = CliRunner()

_TEMPLATE = """\
version: 0.1.0
formats: {card: {canvas: {width: 240px, height: 160px, dpi: 96}}}
preview_data: {}
root:
  type: group
  id: root
  children:
    - id: panel
      type: shape
      shape: rect
      style: {fill: "#d8c8a0"}
      effects: [{name: e2e-grain, params: {amount: 0.1}}]
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
"""


def test_full_extension_lifecycle_and_render(arcavex_home: Path, tmp_path: Path) -> None:
    ext_dir = tmp_path / "e2e-grain"

    scaffold = runner.invoke(app, ["ext", "scaffold", "effect", str(ext_dir), "--json"])
    assert scaffold.exit_code == 0, scaffold.output
    assert (ext_dir / "extension.toml").is_file()

    validate = runner.invoke(app, ["ext", "validate", str(ext_dir), "--json"])
    assert validate.exit_code == 0, validate.output
    assert json.loads(validate.stdout)["ok"] is True

    test = runner.invoke(app, ["ext", "test", str(ext_dir), "--json"])
    assert test.exit_code == 0, test.output
    assert json.loads(test.stdout)["passed"] is True

    add = runner.invoke(app, ["ext", "add", str(ext_dir), "--json"])
    assert add.exit_code == 0, add.output
    assert json.loads(add.stdout)["enabled"] is False  # added disabled

    enable = runner.invoke(app, ["ext", "enable", "e2e-grain", "--json"])
    assert enable.exit_code == 0, enable.output
    assert json.loads(enable.stdout)["enabled"] is True

    listing = runner.invoke(app, ["ext", "list", "--json"])
    assert listing.exit_code == 0
    payload = json.loads(listing.stdout)
    assert payload["extensions"][0]["name"] == "e2e-grain"
    assert payload["extensions"][0]["enabled"] is True
    assert payload["extensions"][0]["components"][0]["name"] == "e2e-grain"

    # Render a template that uses the extension's effect — a fresh facade loads the enabled
    # extension at start, so this proves the component is in the real pipeline like a built-in.
    template = tmp_path / "tpl.yaml"
    template.write_text(_TEMPLATE, encoding="utf-8")
    out = tmp_path / "out.png"
    render = runner.invoke(
        app, ["render", str(template), "--format", "card", "-o", str(out)]
    )
    assert render.exit_code == 0, render.output
    assert out.is_file() and out.stat().st_size > 0


def test_disable_takes_effect_next_start(arcavex_home: Path, tmp_path: Path) -> None:
    ext_dir = tmp_path / "toggle-fx"
    assert runner.invoke(app, ["ext", "scaffold", "effect", str(ext_dir)]).exit_code == 0
    assert runner.invoke(app, ["ext", "add", str(ext_dir)]).exit_code == 0
    assert runner.invoke(app, ["ext", "enable", "toggle-fx"]).exit_code == 0
    disable = runner.invoke(app, ["ext", "disable", "toggle-fx", "--json"])
    assert disable.exit_code == 0
    assert json.loads(disable.stdout)["enabled"] is False
    listing = runner.invoke(app, ["ext", "list", "--json"])
    assert json.loads(listing.stdout)["extensions"][0]["enabled"] is False


def test_enable_unknown_extension_is_diagnosed(arcavex_home: Path) -> None:
    result = runner.invoke(app, ["ext", "enable", "nonexistent", "--json"])
    assert result.exit_code != 0
    codes = [d["code"] for d in json.loads(result.stdout)["diagnostics"]]
    assert "ARC-EXT-040" in codes


def test_validate_flags_disallowed_import(arcavex_home: Path, tmp_path: Path) -> None:
    ext_dir = tmp_path / "reachy"
    runner.invoke(app, ["ext", "scaffold", "effect", str(ext_dir)])
    component = ext_dir / "component.py"
    component.write_text(
        "from arcavex.kernel.ir.units import Rect  # reaches past the SDK\n"
        + component.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["ext", "validate", str(ext_dir), "--json"])
    assert result.exit_code != 0
    codes = [d["code"] for d in json.loads(result.stdout)["diagnostics"]]
    assert "ARC-EXT-030" in codes


def test_validate_flags_nondeterminism(arcavex_home: Path, tmp_path: Path) -> None:
    ext_dir = tmp_path / "randy"
    runner.invoke(app, ["ext", "scaffold", "effect", str(ext_dir)])
    component = ext_dir / "component.py"
    text = component.read_text(encoding="utf-8").replace(
        '        assert isinstance(ctx, RasterContext)',
        "        import random\n        _ = random.random()\n"
        "        assert isinstance(ctx, RasterContext)",
    )
    component.write_text(text, encoding="utf-8")
    result = runner.invoke(app, ["ext", "validate", str(ext_dir), "--json"])
    assert result.exit_code != 0
    codes = [d["code"] for d in json.loads(result.stdout)["diagnostics"]]
    assert "ARC-EXT-031" in codes


ALL_KINDS = (
    "effect",
    "mask",
    "shape",
    "exporter",
    "template_function",
    "decoder",
    "backend",
    "layout_solver",
)


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_scaffold_every_kind_validates_and_tests(
    arcavex_home: Path, tmp_path: Path, kind: str
) -> None:
    """DX-1/CR-1: a fresh scaffold of EVERY documented kind validates and tests green."""
    ext_dir = tmp_path / f"my-{kind}"
    scaffold = runner.invoke(
        app, ["ext", "scaffold", kind, str(ext_dir), "--name", f"my-{kind}", "--json"]
    )
    assert scaffold.exit_code == 0, scaffold.output
    assert (ext_dir / "golden_test.py").is_file(), "every kind must ship a golden_test.py"

    validate = runner.invoke(app, ["ext", "validate", str(ext_dir), "--json"])
    assert validate.exit_code == 0, f"{kind} validate: {validate.output}"
    assert json.loads(validate.stdout)["ok"] is True

    test = runner.invoke(app, ["ext", "test", str(ext_dir), "--json"])
    assert test.exit_code == 0, f"{kind} test: {test.output}"
    assert json.loads(test.stdout)["passed"] is True


def test_collision_with_builtin_caught_at_validate_and_add(
    arcavex_home: Path, tmp_path: Path
) -> None:
    """DX-2/CR-3: a component named after a built-in fails validate AND add, naming both."""
    ext_dir = tmp_path / "dup"
    runner.invoke(app, ["ext", "scaffold", "effect", str(ext_dir), "--name", "dup-fx"])
    manifest = ext_dir / "extension.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'kind = "effect"\nname = "dup-fx"', 'kind = "effect"\nname = "blur"'
        ),
        encoding="utf-8",
    )

    validate = runner.invoke(app, ["ext", "validate", str(ext_dir), "--json"])
    assert validate.exit_code != 0
    vdiags = json.loads(validate.stdout)["diagnostics"]
    dup = next(d for d in vdiags if d["code"] == "ARC-EXT-001")
    assert "built-in 'blur'" in dup["message"] and "dup-fx" in dup["message"]

    add = runner.invoke(app, ["ext", "add", str(ext_dir), "--json"])
    assert add.exit_code != 0
    assert any(d["code"] == "ARC-EXT-001" for d in json.loads(add.stdout)["diagnostics"])


def test_ext_test_implies_validate(arcavex_home: Path, tmp_path: Path) -> None:
    """DX-7: a disallowed import fails `ext test` even though golden_test.py never imports it."""
    ext_dir = tmp_path / "sneaky"
    runner.invoke(app, ["ext", "scaffold", "effect", str(ext_dir)])
    component = ext_dir / "component.py"
    component.write_text(
        "from arcavex.services.doctor import engine_version  # past the SDK surface\n"
        + component.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    test = runner.invoke(app, ["ext", "test", str(ext_dir), "--json"])
    assert test.exit_code != 0
    assert "ARC-EXT-030" in [d["code"] for d in json.loads(test.stdout)["diagnostics"]]


def test_golden_update_workflow(arcavex_home: Path, tmp_path: Path) -> None:
    """DX-5/DX-6: `python golden_test.py --update` writes a golden the next test checks against."""
    import subprocess
    import sys

    ext_dir = tmp_path / "updater"
    runner.invoke(app, ["ext", "scaffold", "effect", str(ext_dir), "--name", "updater"])
    golden = ext_dir / "golden" / "updater.png"
    assert not golden.exists()  # scaffold ships no committed golden yet
    assert runner.invoke(app, ["ext", "test", str(ext_dir)]).exit_code == 0  # passes without one

    update = subprocess.run(
        [sys.executable, "golden_test.py", "--update"],
        cwd=str(ext_dir), capture_output=True, text=True, check=False,
    )
    assert update.returncode == 0, update.stdout + update.stderr
    assert golden.is_file() and golden.stat().st_size > 0

    # The committed golden is now checked on the next test run, and it matches.
    assert runner.invoke(app, ["ext", "test", str(ext_dir), "--json"]).exit_code == 0


def test_reference_extension_validates_and_tests(arcavex_home: Path) -> None:
    """The shipped paper-texture reference extension passes validation and its golden test."""
    validate = runner.invoke(app, ["ext", "validate", str(REFERENCE), "--json"])
    assert validate.exit_code == 0, validate.output
    assert json.loads(validate.stdout)["ok"] is True
    test = runner.invoke(app, ["ext", "test", str(REFERENCE), "--json"])
    assert test.exit_code == 0, test.output
    assert json.loads(test.stdout)["passed"] is True

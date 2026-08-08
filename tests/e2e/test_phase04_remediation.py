"""Phase 4 remediation regression tests.

Covers the required fixes: the project override patch as a hashed manifest input, a
patch-attributed diff, a patch-drift-named rerun (ARC-RUN-002), an asset-change diff,
validate/preview project mode, upgrade previews + structural/perceptual diff with node-path
stale reporting, direct-run list-runs, and the config-precedence chain reaching a render.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcavex.bootstrap import build_facade
from arcavex.clients.cli import app
from arcavex.services.runs import (
    AssetProvenance,
    InputRef,
    RunManifest,
    RunOutput,
    RunStore,
    diff_runs,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO = REPO_ROOT / "tests" / "fixtures" / "basic-poster"
runner = CliRunner()

_GREEN = "- set: nodes.background.style.fill\n  value: '#00ff00'\n"
_BLUE = "- set: nodes.background.style.fill\n  value: '#0000ff'\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def project(arcavex_home: Path, tmp_path: Path):  # noqa: ANN201 - test fixture tuple
    facade = build_facade()
    facade.publish_template(HELLO, "poster", "1.0.0")
    result = facade.create_project(tmp_path / "proj", "demo", "poster@1.0.0")
    assert result.ok, result.diagnostics
    return facade, tmp_path / "proj"


# ---------------------------------------------------------------- P1: patch provenance
def test_patch_is_a_hashed_manifest_input(project) -> None:
    facade, proj = project
    (proj / "overrides" / "poster.patch.yaml").write_text(_GREEN, encoding="utf-8")
    run = facade.render_project(project=proj)
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text("utf-8"))
    assert manifest["patch"] is not None
    assert manifest["patch"]["hash"]
    assert manifest["patch"]["ref"] == "overrides/poster.patch.yaml"


def test_no_patch_leaves_manifest_patch_null(project) -> None:
    facade, proj = project
    run = facade.render_project(project=proj)
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text("utf-8"))
    assert manifest["patch"] is None


def test_diff_attributes_a_patch_only_change(project) -> None:
    facade, proj = project
    (proj / "overrides" / "poster.patch.yaml").write_text(_GREEN, encoding="utf-8")
    green = facade.render_project(project=proj)
    (proj / "overrides" / "poster.patch.yaml").write_text(_BLUE, encoding="utf-8")
    blue = facade.render_project(project=proj)
    diff = facade.diff_runs(Path(green.run_dir), Path(blue.run_dir))
    # Pixels differ AND the override change is named in metadata (no more "no metadata changes").
    assert any(not o.identical for o in diff.outputs)
    fields = {m.field for m in diff.metadata}
    assert "overrides.hash" in fields


def test_rerun_names_patch_drift(project) -> None:
    facade, proj = project
    (proj / "overrides" / "poster.patch.yaml").write_text(_GREEN, encoding="utf-8")
    run = facade.render_project(project=proj)
    # Change the override on disk, then rerun the recorded run.
    (proj / "overrides" / "poster.patch.yaml").write_text(_BLUE, encoding="utf-8")
    rr = facade.rerun(Path(run.run_dir))
    assert rr.ok and not rr.reproduced and rr.engine_match and rr.platform_match
    assert any("overrides" in reason for reason in rr.drift)
    assert any(d.code == "ARC-RUN-002" for d in rr.diagnostics)
    repro = json.loads((Path(rr.run_dir) / "reproduction.json").read_text("utf-8"))
    assert any("overrides" in reason for reason in repro["input_drift"])


def test_diff_attributes_an_asset_change(tmp_path: Path) -> None:
    """CR-2: an asset-only change (same outputs, different asset sha) is named in the diff."""
    store = RunStore()

    def manifest(asset_sha: str) -> RunManifest:
        return RunManifest(
            run_id="r", created="t", engine_version="1", platform="win-x86_64", ir_version="1.0",
            kind="direct", template=InputRef(ref="t", hash="h"),
            outputs=[RunOutput(
                name="out.png", format="square", sha256="same", width=1, height=1, bytes=1,
                seed=0, data_hash="d",
            )],
            assets=[AssetProvenance(
                path="logo.png", sha256=asset_sha, mime="image/png", width=1, height=1, bytes=1,
            )],
        )

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    store.write_manifest(a, manifest("aaa"))
    store.write_manifest(b, manifest("bbb"))
    report = diff_runs(a, b, store, lambda _p, _q: 0.0)
    assert any(m.field == "asset[logo.png]" for m in report.metadata)


# ------------------------------------------------------------------ DX-1: project mode
def test_validate_project_mode(project) -> None:
    facade, proj = project
    result = runner.invoke(app, ["validate", "--project", str(proj), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"]


def test_validate_project_mode_surfaces_broken_data(project) -> None:
    facade, proj = project
    # Break the project's data so project-mode validate reports it (not a Typer usage error).
    (proj / "data" / "demo.yaml").write_text("title: 123\nsubtitle: [not, a, string]\n", "utf-8")
    result = runner.invoke(app, ["validate", "--project", str(proj), "--json"])
    payload = json.loads(result.stdout)
    assert not payload["ok"] and payload["diagnostics"]


def test_validate_bare_no_project_is_helpful(arcavex_home: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "--project", str(tmp_path)])
    assert result.exit_code == 1 and "ARC-PRJ-001" in result.output


def test_preview_project_mode(project) -> None:
    facade, proj = project
    report = facade.preview_project(project=proj)
    assert report.ok and len(report.previews) == 2
    for res in report.previews:
        assert res.ok and res.output_path and Path(res.output_path).is_file()


# ---------------------------------------------------------- DX-4/DX-5: upgrade preview
def _publish_v2_renaming_background(facade, tmp_path: Path) -> None:
    v2 = tmp_path / "poster-v2"
    shutil.copytree(HELLO, v2)
    text = (v2 / "template.yaml").read_text("utf-8").replace("id: background", "id: backdrop")
    (v2 / "template.yaml").write_text(text, encoding="utf-8")
    facade.publish_template(v2, "poster", "2.0.0", set_default=False)


def test_upgrade_reports_node_path_and_structural_diff(arcavex_home: Path, tmp_path: Path) -> None:
    facade = build_facade()
    facade.publish_template(HELLO, "poster", "1.0.0")
    _publish_v2_renaming_background(facade, tmp_path)
    facade.create_project(tmp_path / "proj", "demo", "poster@1.0.0")
    (tmp_path / "proj" / "overrides" / "poster.patch.yaml").write_text(_GREEN, encoding="utf-8")
    report = facade.upgrade_project("2.0.0", apply=False, project=tmp_path / "proj")
    assert report.ok and not report.applied
    # DX-5: stale entry names the node path and id, not just an op index.
    assert report.stale_paths == ["nodes.background.style.fill"]
    stale = report.stale[0]
    assert stale.node_id == "background" and stale.path == "nodes.background.style.fill"
    assert stale.op == "project.patch[0]"
    # Structural node diff: background removed, backdrop added.
    assert "background" in report.removed_nodes and "backdrop" in report.added_nodes
    # DX-4: comparable previews are produced with a perceptual score, patch dropped as stale.
    assert report.outputs and all(o.dssim is not None for o in report.outputs)
    assert all(o.patch_applied is False for o in report.outputs)


def test_upgrade_previews_when_patch_still_applies(arcavex_home: Path, tmp_path: Path) -> None:
    facade = build_facade()
    facade.publish_template(HELLO, "poster", "1.0.0")
    # v2 keeps 'background' but changes its fill, so the patch still applies and pixels differ.
    v2 = tmp_path / "poster-v2"
    shutil.copytree(HELLO, v2)
    facade.publish_template(v2, "poster", "2.0.0", set_default=False)
    facade.create_project(tmp_path / "proj", "demo", "poster@1.0.0")
    report = facade.upgrade_project("2.0.0", apply=False, project=tmp_path / "proj")
    assert report.ok and report.outputs and not report.stale_paths
    assert all(o.patch_applied for o in report.outputs)


# ------------------------------------------------------------- DX-7: direct-run listing
def test_list_runs_direct_mode_by_path(arcavex_home: Path, tmp_path: Path) -> None:
    facade = build_facade()
    out = tmp_path / "out"
    rec = facade.record_render(HELLO / "template.yaml", format_name="square", outputs_root=out)
    assert rec.ok
    # No project here: list-runs --path must still find the recorded direct run.
    listed = runner.invoke(app, ["list-runs", "--path", str(out), "--json"])
    assert listed.exit_code == 0, listed.output
    runs = json.loads(listed.stdout)["runs"]
    assert len(runs) == 1 and runs[0]["kind"] == "direct"


# --------------------------------------------------------------- DX-8: config reaches render
def test_config_toml_dpi_reaches_render(arcavex_home: Path, tmp_path: Path) -> None:
    (arcavex_home / "config.toml").write_text("[render]\ndpi = 150\n", encoding="utf-8")
    facade = build_facade()
    facade.publish_template(HELLO, "poster", "1.0.0")
    facade.create_project(tmp_path / "proj", "demo", "poster@1.0.0")
    run = facade.render_project(project=tmp_path / "proj")
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text("utf-8"))
    assert manifest["dpi"] == 150  # resolved through config.toml (no CLI/env/project override)


def test_project_yaml_dpi_beats_config(arcavex_home: Path, tmp_path: Path) -> None:
    (arcavex_home / "config.toml").write_text("[render]\ndpi = 150\n", encoding="utf-8")
    facade = build_facade()
    facade.publish_template(HELLO, "poster", "1.0.0")
    facade.create_project(tmp_path / "proj", "demo", "poster@1.0.0")
    proj_yaml = tmp_path / "proj" / "project.yaml"
    proj_yaml.write_text(proj_yaml.read_text("utf-8") + "dpi: 210\n", encoding="utf-8")
    run = facade.render_project(project=tmp_path / "proj")
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text("utf-8"))
    assert manifest["dpi"] == 210


def test_manifest_timings_are_populated(project) -> None:
    facade, proj = project
    run = facade.render_project(project=proj)
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text("utf-8"))
    assert set(manifest["timings_ms"]) == {"compile_ms", "render_ms"}
    assert all(v >= 0 for v in manifest["timings_ms"].values())

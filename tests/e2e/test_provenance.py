"""End-to-end provenance tests: manifests, rerun byte-identity, diff, upgrade, patch layer.

These exercise the full engine through the facade with an isolated ``$ARCAVEX_HOME`` (the
``arcavex_home`` fixture). They cover the Phase 4 exit criteria: a manifest captures every input
by hash, a same-platform rerun is byte-identical, a diff reports pixels and metadata separately,
an upgrade detects stale patch paths, and the project override layer changes the render.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.services.runs import RunStore, format_run_id, utc_now

REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO = REPO_ROOT / "tests" / "fixtures" / "basic-poster"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def project(arcavex_home: Path, tmp_path: Path):  # noqa: ANN201 - test fixture tuple
    """Publish the poster template and scaffold a project pinned to it; return (facade, dir)."""
    facade = build_facade()
    facade.publish_template(HELLO, "poster", "1.0.0")
    result = facade.create_project(tmp_path / "proj", "demo", "poster@1.0.0")
    assert result.ok, result.diagnostics
    return facade, tmp_path / "proj"


def test_manifest_captures_every_input(project) -> None:
    facade, proj = project
    run = facade.render_project(project=proj)
    assert run.ok, run.diagnostics
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["engine_version"] and manifest["platform"] and manifest["ir_version"]
    assert manifest["template"]["hash"] and manifest["template_is_library"] is True
    assert manifest["fonts_hash"] and manifest["fonts"]
    assert manifest["assets"], "logo.png asset should be recorded by hash"
    assert set(manifest["resolved_data"]) == {""}  # one base (no-locale) snapshot
    for out in manifest["outputs"]:
        assert out["sha256"] and out["width"] > 0 and out["height"] > 0 and out["data_hash"]
        assert (Path(run.run_dir) / out["name"]).is_file()


def test_rerun_is_byte_identical(project) -> None:
    facade, proj = project
    run = facade.render_project(project=proj)
    original = {Path(o).name: _sha(Path(o)) for o in run.outputs}
    rr = facade.rerun(Path(run.run_dir))
    assert rr.ok and rr.reproduced and not rr.mismatches
    assert rr.run_dir != run.run_dir  # a new surrounding run directory
    for name, digest in original.items():
        assert _sha(Path(rr.run_dir) / name) == digest
    repro = json.loads((Path(rr.run_dir) / "reproduction.json").read_text(encoding="utf-8"))
    assert repro["reproduced"] is True and repro["source_run"]


def test_output_bytes_independent_of_time(project) -> None:
    """Image bytes carry no timestamp: two runs at different times share output hashes."""
    facade, proj = project
    a = facade.render_project(project=proj)
    b = facade.render_project(project=proj)
    assert a.run_dir != b.run_dir
    by_a = {Path(o).name: _sha(Path(o)) for o in a.outputs}
    by_b = {Path(o).name: _sha(Path(o)) for o in b.outputs}
    assert by_a == by_b


def test_diff_identical_then_changed(project) -> None:
    facade, proj = project
    a = facade.render_project(project=proj)
    same = facade.diff_runs(Path(a.run_dir), Path(a.run_dir))
    assert all(o.identical for o in same.outputs) and not same.metadata
    # Change the data and re-render: pixels differ and the data metadata field changes.
    (proj / "data" / "demo.yaml").write_text(
        "title: Totally Different\nsubtitle: New\n", encoding="utf-8"
    )
    b = facade.render_project(project=proj)
    changed = facade.diff_runs(Path(a.run_dir), Path(b.run_dir))
    assert any(not o.identical and (o.dssim or 0) > 0 for o in changed.outputs)
    assert any(m.field.startswith("data") for m in changed.metadata)


def test_project_override_layer_changes_render(project) -> None:
    facade, proj = project
    baseline = facade.render_project(project=proj)
    base_sha = {Path(o).name: _sha(Path(o)) for o in baseline.outputs}
    (proj / "overrides" / "poster.patch.yaml").write_text(
        "- set: nodes.background.style.fill\n  value: '#00ff00'\n", encoding="utf-8"
    )
    patched = facade.render_project(project=proj)
    patched_sha = {Path(o).name: _sha(Path(o)) for o in patched.outputs}
    assert base_sha != patched_sha  # the override layer altered the pixels
    # The data snapshot is unchanged — the patch is structural, not data (provenance check).
    mb = json.loads((Path(baseline.run_dir) / "manifest.json").read_text("utf-8"))
    mp = json.loads((Path(patched.run_dir) / "manifest.json").read_text("utf-8"))
    assert mb["resolved_data"] == mp["resolved_data"]


def test_upgrade_detects_stale_patch_path(arcavex_home: Path, tmp_path: Path) -> None:
    facade = build_facade()
    facade.publish_template(HELLO, "poster", "1.0.0")
    # Publish a v2 whose 'background' node was renamed, so a patch addressing it goes stale.
    v2 = tmp_path / "poster-v2"
    shutil.copytree(HELLO, v2)
    text = (v2 / "template.yaml").read_text(encoding="utf-8").replace(
        "id: background", "id: backdrop"
    )
    (v2 / "template.yaml").write_text(text, encoding="utf-8")
    facade.publish_template(v2, "poster", "2.0.0", set_default=False)
    facade.create_project(tmp_path / "proj", "demo", "poster@1.0.0")
    (tmp_path / "proj" / "overrides" / "poster.patch.yaml").write_text(
        "- set: nodes.background.style.fill\n  value: '#000000'\n", encoding="utf-8"
    )
    report = facade.upgrade_project("2.0.0", apply=False, project=tmp_path / "proj")
    assert report.ok and report.stale_paths and not report.applied
    # Pin is unchanged until explicitly applied.
    assert facade.project_status(project=tmp_path / "proj").template == "poster@1.0.0"
    applied = facade.upgrade_project("2.0.0", apply=True, project=tmp_path / "proj")
    assert applied.applied
    assert facade.project_status(project=tmp_path / "proj").template == "poster@2.0.0"


def test_direct_record_render_and_rerun(arcavex_home: Path, tmp_path: Path) -> None:
    facade = build_facade()
    rec = facade.record_render(
        HELLO / "template.yaml", format_name="square", outputs_root=tmp_path / "out"
    )
    assert rec.ok and (Path(rec.run_dir) / "manifest.json").is_file()
    manifest = json.loads((Path(rec.run_dir) / "manifest.json").read_text("utf-8"))
    assert manifest["kind"] == "direct" and manifest["template_is_library"] is False
    original = {Path(o).name: _sha(Path(o)) for o in rec.outputs}
    rr = facade.rerun(Path(rec.run_dir))
    assert rr.reproduced
    for name, digest in original.items():
        assert _sha(Path(rr.run_dir) / name) == digest


def test_detach_disables_upgrades(project) -> None:
    facade, proj = project
    detached = facade.detach_template(project=proj)
    assert detached.ok and detached.template == "templates/poster"
    assert (proj / "templates" / "poster" / "template.yaml").is_file()
    assert any(d.code == "ARC-PRJ-007" for d in detached.diagnostics)
    # A detached project can still render, but upgrades are refused.
    assert facade.render_project(project=proj).ok
    upgrade = facade.upgrade_project("2.0.0", project=proj)
    assert not upgrade.ok and any(d.code == "ARC-PRJ-006" for d in upgrade.diagnostics)


def test_concurrent_renders_get_distinct_run_dirs(tmp_path: Path) -> None:
    """Two runs with the same base id must land in distinct directories without clobbering."""
    store = RunStore()
    outputs = tmp_path / "outputs"
    run_id = format_run_id(utc_now(), "abc123")
    dir_a, id_a = store.new_run_dir(outputs, run_id)
    dir_b, id_b = store.new_run_dir(outputs, run_id)
    assert dir_a != dir_b and id_a != id_b
    assert dir_a.is_dir() and dir_b.is_dir()

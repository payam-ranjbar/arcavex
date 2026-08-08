"""Project snapshot contract and real-filesystem behavior tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel import api
from arcavex.kernel.api import (
    DoctorReport,
    EngineHandshakeReport,
    EngineIdentity,
    EnginePaths,
    Facade,
    ProjectSnapshotReport,
)
from arcavex.kernel.registry import Registries
from arcavex.services.library import Library
from arcavex.services.projects import ProjectService

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASIC_TEMPLATE = _REPO_ROOT / "tests/fixtures/basic-poster"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a hand-authored local-template project with ignored working artifacts."""
    root = tmp_path / "campaign"
    for directory in (
        "assets",
        "cache",
        "data",
        "outputs/run-1",
        "overrides",
        "template",
        ".arcavex/pending",
        ".arcavex/cache",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "project.yaml").write_text(
        """name: launch
template: ./template
style: midnight@1.0.0
formats: [story, square]
locales: [fa, en]
data: data/content.yaml
dpi: 144
status: review
tags: [summer]
automation: {mode: review}
""",
        encoding="utf-8",
    )
    (root / "project.ui.yaml").write_text(
        "version: 1\nlayers: {title: {display_name: Headline}}\n", encoding="utf-8"
    )
    (root / "template/template.yaml").write_bytes(b"title\r\n")
    (root / "template/schema.yaml").write_text("title: {type: string}\n", encoding="utf-8")
    (root / "data/content.yaml").write_bytes(b"title\r\n")
    (root / "overrides/template.patch.yaml").write_text(
        "- set: nodes.title.text\n  value: Launch\n", encoding="utf-8"
    )
    (root / "assets/hero.bin").write_bytes(bytes((0, 13, 10, 255)))
    (root / "outputs/run-1/render.png").write_bytes(b"ignored output")
    (root / "cache/preview.png").write_bytes(b"ignored cache")
    (root / ".arcavex/pending/command.json").write_text("{}\n", encoding="utf-8")
    (root / ".arcavex/cache/index.json").write_text("{}\n", encoding="utf-8")
    return root


def _service(library: Library | None = None):
    from arcavex.services.project_snapshot import ProjectSnapshotService

    projects = ProjectService(library)
    return ProjectSnapshotService(projects)


def _tree_state(root: Path) -> tuple[tuple[str, bool, bytes | None, int], ...]:
    """Capture names, contents, and mtimes without deriving expectations from snapshot code."""
    entries: list[tuple[str, bool, bytes | None, int]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        entries.append(
            (
                path.relative_to(root).as_posix(),
                path.is_dir(),
                None if path.is_dir() else path.read_bytes(),
                path.stat().st_mtime_ns,
            )
        )
    return tuple(entries)


def _handshake(capabilities: list[str]) -> EngineHandshakeReport:
    return EngineHandshakeReport(
        ok=True,
        identity=EngineIdentity(engine_version="0.1.0"),
        mcp_contract_version="2025-06-18",
        accepted_ir_versions=["1.0"],
        produced_ir_version="1.0",
        extension_sdk_version="1.0",
        capabilities=capabilities,
        paths=EnginePaths(
            home="C:/Arcavex/home",
            assets="C:/Arcavex/home/assets",
            cache="C:/Arcavex/home/cache",
            extensions="C:/Arcavex/home/extensions",
            fonts="C:/Arcavex/home/fonts",
            styles="C:/Arcavex/home/styles",
            templates="C:/Arcavex/home/templates",
        ),
        doctor=DoctorReport(ok=True, engine_version="0.1.0", checks=[]),
    )


def test_snapshot_contract_models_expose_metadata_targets_revisions_and_sources() -> None:
    """Removing a desktop snapshot field must break the shared serialized contract."""
    entry = api.RevisionManifestEntry(path="data/content.yaml", sha256="a" * 64, bytes=12)
    target = api.ProjectTarget(format="story", locale="fa")
    source = api.ProjectSourceFile(
        path="data/content.yaml",
        resolved_path="C:/campaign/data/content.yaml",
        role="data",
        project_owned=True,
        sha256="a" * 64,
    )

    report = api.ProjectSnapshotReport(
        ok=True,
        canonical_path="C:/campaign",
        name="launch",
        template="template",
        style="midnight@1.0.0",
        data="data/content.yaml",
        dpi=144,
        formats=["story"],
        locales=["fa"],
        targets=[target],
        default_target=target,
        status="review",
        tags=["summer"],
        project_revision="b" * 64,
        render_revision="c" * 64,
        project_manifest=[entry],
        render_manifest=[entry],
        source_files=[source],
        capabilities=["project.snapshot"],
    )

    assert report.model_dump(mode="json") == {
        "response_version": 1,
        "ok": True,
        "canonical_path": "C:/campaign",
        "name": "launch",
        "template": "template",
        "style": "midnight@1.0.0",
        "data": "data/content.yaml",
        "dpi": 144,
        "formats": ["story"],
        "locales": ["fa"],
        "targets": [{"format": "story", "locale": "fa"}],
        "default_target": {"format": "story", "locale": "fa"},
        "status": "review",
        "tags": ["summer"],
        "project_revision": "b" * 64,
        "render_revision": "c" * 64,
        "project_manifest": [
            {"path": "data/content.yaml", "sha256": "a" * 64, "bytes": 12}
        ],
        "render_manifest": [
            {"path": "data/content.yaml", "sha256": "a" * 64, "bytes": 12}
        ],
        "source_files": [
            {
                "path": "data/content.yaml",
                "resolved_path": "C:/campaign/data/content.yaml",
                "role": "data",
                "project_owned": True,
                "sha256": "a" * 64,
            }
        ],
        "capabilities": ["project.snapshot"],
        "diagnostics": [],
    }


def test_local_project_snapshot_is_canonical_complete_deterministic_and_read_only(
    project_dir: Path,
) -> None:
    """Dropping an owned input, changing target order, or writing on open must fail."""
    before = _tree_state(project_dir)

    report = _service().snapshot(
        project=project_dir / ".", capabilities=["render.preview", "project.snapshot"]
    )

    assert report.ok
    assert report.canonical_path == str(project_dir.resolve())
    assert (report.name, report.template, report.style, report.data, report.dpi) == (
        "launch",
        "./template",
        "midnight@1.0.0",
        "data/content.yaml",
        144,
    )
    assert report.status == "review"
    assert report.tags == ["summer"]
    assert report.targets == [
        api.ProjectTarget(format="story", locale="fa"),
        api.ProjectTarget(format="story", locale="en"),
        api.ProjectTarget(format="square", locale="fa"),
        api.ProjectTarget(format="square", locale="en"),
    ]
    assert report.default_target == api.ProjectTarget(format="story", locale="fa")
    assert report.capabilities == ["project.snapshot", "render.preview"]
    assert [entry.path for entry in report.project_manifest] == [
        "assets/hero.bin",
        "data/content.yaml",
        "overrides/template.patch.yaml",
        "project.ui.yaml",
        "project.yaml",
        "template/schema.yaml",
        "template/template.yaml",
    ]
    assert [entry.path for entry in report.render_manifest] == [
        "@project/render-inputs.json",
        "assets/hero.bin",
        "data/content.yaml",
        "overrides/template.patch.yaml",
        "template/schema.yaml",
        "template/template.yaml",
    ]
    entry_hashes = {entry.path: entry.sha256 for entry in report.project_manifest}
    assert entry_hashes["data/content.yaml"] == (
        "1ec72b6861fee9926d828a734ddbd533a1eb1a983d42acec571720deb2b92018"
    )
    assert entry_hashes["assets/hero.bin"] == (
        "d0585d080e1306012af277c93878dfdff7c00b3e8602893d8361bbcc6e8a791c"
    )
    assert [source.path for source in report.source_files] == [
        "assets/hero.bin",
        "data/content.yaml",
        "overrides/template.patch.yaml",
        "project.ui.yaml",
        "project.yaml",
        "template/schema.yaml",
        "template/template.yaml",
    ]
    assert all(source.project_owned for source in report.source_files)
    assert len(report.project_revision or "") == 64
    assert len(report.render_revision or "") == 64
    assert _tree_state(project_dir) == before


def test_snapshot_reports_a_missing_declared_render_input(project_dir: Path) -> None:
    """A missing declared data file must be named explicitly instead of silently omitted."""
    (project_dir / "data/content.yaml").unlink()

    report = _service().snapshot(project=project_dir, capabilities=[])

    assert not report.ok
    actual = [
        (diag.code, diag.source.file if diag.source else None)
        for diag in report.diagnostics
    ]
    assert actual == [("ARC-PRJ-005", str((project_dir / "data/content.yaml").resolve()))]
    assert report.project_revision is not None
    assert report.render_revision is not None


def test_snapshot_reports_missing_template_yaml_in_a_declared_directory(
    project_dir: Path,
) -> None:
    """A template directory without its authored root file must be an explicit diagnostic."""
    (project_dir / "template/template.yaml").unlink()
    (project_dir / "template/schema.yaml").unlink()

    report = _service().snapshot(project=project_dir, capabilities=[])

    assert not report.ok
    assert [(diag.code, diag.source.file) for diag in report.diagnostics if diag.source] == [
        ("ARC-PRJ-005", str((project_dir / "template/template.yaml").resolve()))
    ]


def test_library_template_is_reported_as_external_source_not_project_owned(tmp_path: Path) -> None:
    """A pinned library source path is diagnostic metadata, not an owned manifest entry."""
    authored = tmp_path / "authored"
    authored.mkdir()
    (authored / "template.yaml").write_text("version: 0.1.0\n", encoding="utf-8")
    library = Library(tmp_path / "library")
    resolved = library.publish(authored, "poster", "1.0.0")
    project = tmp_path / "campaign"
    project.mkdir()
    (project / "project.yaml").write_text(
        "name: launch\ntemplate: poster@1.0.0\nformats: [square]\nlocales: []\n",
        encoding="utf-8",
    )

    report = _service(library).snapshot(project=project, capabilities=["project.snapshot"])

    external = [source for source in report.source_files if not source.project_owned]
    assert report.ok
    assert external == [
        api.ProjectSourceFile(
            path="poster@1.0.0",
            resolved_path=str(resolved.path.resolve()),
            role="template",
            project_owned=False,
            sha256=None,
        )
    ]
    assert all(not entry.path.startswith("../") for entry in report.project_manifest)
    assert [entry.path for entry in report.render_manifest] == [
        "@project/render-inputs.json"
    ]


def test_external_local_template_content_is_render_hashed_but_not_project_owned(
    tmp_path: Path,
) -> None:
    """Changing an external local template must invalidate render without faking ownership."""
    authored = tmp_path / "shared/template"
    shutil.copytree(_BASIC_TEMPLATE, authored)
    project = ProjectService().create(
        tmp_path / "campaign", "launch", str(authored)
    )

    before = _service().snapshot(project=project.root)
    (authored / "template.yaml").write_bytes(
        (authored / "template.yaml").read_bytes() + b"\n# revised\n"
    )
    after = _service().snapshot(project=project.root)

    external = [source for source in before.source_files if not source.project_owned]
    assert before.ok and after.ok
    assert [source.path for source in external] == [
        "@external/template/data.yaml",
        "@external/template/logo.png",
        "@external/template/template.yaml",
    ]
    assert all(source.role == "template" and source.sha256 for source in external)
    assert "@external/template/template.yaml" in {
        entry.path for entry in before.render_manifest
    }
    assert before.project_revision == after.project_revision
    assert before.render_revision != after.render_revision


def test_missing_external_local_template_is_a_non_owned_source_diagnostic(
    tmp_path: Path,
) -> None:
    """A missing external template root file must fail instead of producing a usable snapshot."""
    authored = tmp_path / "shared/template"
    shutil.copytree(_BASIC_TEMPLATE, authored)
    project = ProjectService().create(
        tmp_path / "campaign", "launch", str(authored)
    )
    (authored / "template.yaml").unlink()

    report = _service().snapshot(project=project.root)

    missing = [
        source
        for source in report.source_files
        if source.path == "@external/template/template.yaml"
    ]
    assert not report.ok
    assert [(diag.code, diag.source.file) for diag in report.diagnostics if diag.source] == [
        ("ARC-PRJ-005", str((authored / "template.yaml").resolve()))
    ]
    assert len(missing) == 1
    assert not missing[0].project_owned
    assert missing[0].sha256 is None


def test_external_data_content_is_render_hashed_and_reports_actual_ownership(
    tmp_path: Path,
) -> None:
    """An existing external data file must not crash or enter the owned project manifest."""
    project = tmp_path / "campaign"
    (project / "template").mkdir(parents=True)
    (project / "template/template.yaml").write_text("version: 0.1.0\n", encoding="utf-8")
    shared_data = tmp_path / "shared/content.yaml"
    shared_data.parent.mkdir()
    shared_data.write_text("title: Launch\n", encoding="utf-8")
    (project / "project.yaml").write_text(
        "name: launch\ntemplate: ./template\ndata: ../shared/content.yaml\n"
        "formats: [square]\nlocales: []\n",
        encoding="utf-8",
    )

    try:
        before = _service().snapshot(project=project)
    except ValueError as exc:
        pytest.fail(f"external data escaped snapshot path handling: {exc}")
    shared_data.write_text("title: Revised\n", encoding="utf-8")
    after = _service().snapshot(project=project)

    source = next(item for item in before.source_files if item.path == "@external/data")
    assert before.ok and after.ok
    assert not source.project_owned
    assert source.resolved_path == str(shared_data.resolve())
    assert source.sha256
    assert "@external/data" in {entry.path for entry in before.render_manifest}
    assert "@external/data" not in {entry.path for entry in before.project_manifest}
    assert before.project_revision == after.project_revision
    assert before.render_revision != after.render_revision


def test_missing_external_data_is_a_non_owned_source_diagnostic(tmp_path: Path) -> None:
    """A missing external data path must retain its role label and actual ownership."""
    project = tmp_path / "campaign"
    (project / "template").mkdir(parents=True)
    (project / "template/template.yaml").write_text("version: 0.1.0\n", encoding="utf-8")
    missing_data = tmp_path / "shared/missing.yaml"
    (project / "project.yaml").write_text(
        "name: launch\ntemplate: ./template\ndata: ../shared/missing.yaml\n"
        "formats: [square]\nlocales: []\n",
        encoding="utf-8",
    )

    report = _service().snapshot(project=project)

    source = next(item for item in report.source_files if item.path == "@external/data")
    assert not report.ok
    assert not source.project_owned
    assert source.resolved_path == str(missing_data.resolve())
    assert source.sha256 is None
    assert [(diag.code, diag.source.file) for diag in report.diagnostics if diag.source] == [
        ("ARC-PRJ-005", str(missing_data.resolve()))
    ]


def test_inactive_override_changes_project_revision_only(project_dir: Path) -> None:
    """Only the patch selected by Project.patch_path may invalidate the render revision."""
    inactive = project_dir / "overrides/unused.patch.yaml"
    inactive.write_text("- remove: nodes.footer\n", encoding="utf-8")
    before = _service().snapshot(project=project_dir)

    inactive.write_text("- remove: nodes.title\n", encoding="utf-8")
    after = _service().snapshot(project=project_dir)

    assert "overrides/unused.patch.yaml" in {
        entry.path for entry in before.project_manifest
    }
    assert "overrides/unused.patch.yaml" not in {
        entry.path for entry in before.render_manifest
    }
    assert before.project_revision != after.project_revision
    assert before.render_revision == after.render_revision


def test_utf8_text_asset_line_endings_normalize_without_revision_churn(
    project_dir: Path,
) -> None:
    """Equivalent UTF-8 text asset checkouts must share project and render revisions."""
    asset = project_dir / "assets/overlay.svg"
    asset.write_bytes(b"<svg>\r\n<path/>\r\n</svg>\r\n")
    crlf = _service().snapshot(project=project_dir)

    asset.write_bytes(b"<svg>\n<path/>\n</svg>\n")
    lf = _service().snapshot(project=project_dir)

    assert crlf.project_manifest == lf.project_manifest
    assert crlf.render_manifest == lf.render_manifest
    assert crlf.project_revision == lf.project_revision
    assert crlf.render_revision == lf.render_revision


@pytest.mark.parametrize("asset_name", ["behavior.js", "settings.ini", "README"])
def test_utf8_text_asset_detection_is_independent_of_filename(
    project_dir: Path, asset_name: str
) -> None:
    """Unknown-extension and extensionless UTF-8 assets must normalize checkout endings."""
    asset = project_dir / "assets" / asset_name
    asset.write_bytes(b"first line\r\nsecond line\r\n")
    crlf = _service().snapshot(project=project_dir)

    asset.write_bytes(b"first line\nsecond line\n")
    lf = _service().snapshot(project=project_dir)

    assert crlf.project_manifest == lf.project_manifest
    assert crlf.render_manifest == lf.render_manifest
    assert crlf.project_revision == lf.project_revision
    assert crlf.render_revision == lf.render_revision


def test_utf8_decodable_control_bearing_asset_remains_byte_exact(
    project_dir: Path,
) -> None:
    """Strictly decodable binary controls must prevent text line-ending normalization."""
    asset = project_dir / "assets/control-payload.dat"
    asset.write_bytes(b"\x00META\r\n\x01")
    crlf = _service().snapshot(project=project_dir)

    asset.write_bytes(b"\x00META\n\x01")
    lf = _service().snapshot(project=project_dir)

    crlf_entry = next(
        entry for entry in crlf.project_manifest if entry.path == "assets/control-payload.dat"
    )
    lf_entry = next(
        entry for entry in lf.project_manifest if entry.path == "assets/control-payload.dat"
    )
    assert (crlf_entry.sha256, crlf_entry.bytes) == (
        "a459df774b1d251928987b9ed7ae758b8904324cba64ee28a63a4f01f8613435",
        8,
    )
    assert (lf_entry.sha256, lf_entry.bytes) == (
        "1fe864883e0bab9b0c05158fbbc3598a5526d9b0fb01687f6f37230dbbd99e39",
        7,
    )
    assert crlf.project_revision != lf.project_revision
    assert crlf.render_revision != lf.render_revision


def test_template_file_symlink_outside_root_uses_link_location_without_crashing(
    project_dir: Path,
) -> None:
    """An escaping template symlink must hash its target under the stable authored link path."""
    external = project_dir.parent / "shared/behavior.js"
    external.parent.mkdir()
    external.write_text("const value = 1;\n", encoding="utf-8")
    link = project_dir / "template/shared-behavior.js"
    try:
        link.symlink_to(external)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"platform cannot create file symlinks: {exc}")

    before = _service().snapshot(project=project_dir)
    external.write_text("const value = 2;\n", encoding="utf-8")
    after = _service().snapshot(project=project_dir)

    source = next(
        item for item in before.source_files if item.path == "template/shared-behavior.js"
    )
    assert before.ok and after.ok
    assert source.resolved_path == str(external.resolve())
    assert not source.project_owned
    assert source.sha256
    assert "template/shared-behavior.js" in {
        entry.path for entry in before.render_manifest
    }
    assert "template/shared-behavior.js" not in {
        entry.path for entry in before.project_manifest
    }
    assert before.project_revision == after.project_revision
    assert before.render_revision != after.render_revision


def test_equivalent_local_path_spellings_share_render_projection(project_dir: Path) -> None:
    """Lexically different references to the same local inputs must share a render key."""
    canonical = _service().snapshot(project=project_dir)
    manifest = (project_dir / "project.yaml").read_text(encoding="utf-8")
    (project_dir / "project.yaml").write_text(
        manifest.replace("template: ./template", "template: template/../template").replace(
            "data: data/content.yaml", "data: ./data/../data/content.yaml"
        ),
        encoding="utf-8",
    )

    equivalent = _service().snapshot(project=project_dir)

    assert canonical.project_revision != equivalent.project_revision
    assert canonical.render_manifest == equivalent.render_manifest
    assert canonical.render_revision == equivalent.render_revision


def test_facade_snapshot_uses_capabilities_from_the_handshake_service() -> None:
    """Snapshot capabilities must come from the reviewed handshake, never version guessing."""
    expected_capabilities = ["future.experimental", "project.snapshot"]

    class DesktopFake:
        def handshake(self) -> EngineHandshakeReport:
            return _handshake(expected_capabilities)

    class SnapshotOrchestratorFake:
        def project_snapshot(
            self,
            start: Path | None,
            project: Path | None,
            capabilities: list[str],
        ) -> ProjectSnapshotReport:
            return ProjectSnapshotReport(ok=True, capabilities=capabilities)

    facade = Facade(
        Registries(),
        cast(Any, object()),
        cast(Any, lambda request: None),
        orchestrator=cast(Any, SnapshotOrchestratorFake()),
        desktop=DesktopFake(),
    )

    report = facade.project_snapshot(project=Path("C:/campaign"))

    assert report.ok
    assert report.capabilities == expected_capabilities


def test_bootstrap_wires_the_live_snapshot_service(project_dir: Path) -> None:
    """Production composition must expose the service and advertise its named capability."""
    report = build_facade().project_snapshot(project=project_dir)

    assert report.ok
    assert report.canonical_path == str(project_dir.resolve())
    assert "project.snapshot" in report.capabilities


def test_project_snapshot_schema_export_is_deterministic_and_matches_model() -> None:
    """Desktop schema export must be canonical and generated from the shared snapshot model."""
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/export_desktop_schemas.py"
    schema_path = root / "schemas/desktop/project-snapshot.schema.json"

    first_run = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
        check=False,
    )
    assert first_run.returncode == 0, first_run.stderr
    first = schema_path.read_bytes()
    second_run = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
        check=False,
    )
    assert second_run.returncode == 0, second_run.stderr
    second = schema_path.read_bytes()
    expected = (
        json.dumps(
            ProjectSnapshotReport.model_json_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    assert first == second == expected
    assert first.endswith(b"\n")

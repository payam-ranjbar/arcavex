"""Project, library, and provenance orchestration (spec §5).

This is the service that turns projects into recorded runs and back again: it drives the
compiler and the injected render pipeline, captures every input by hash into a run manifest,
and implements rerun, diff, batch, upgrade, publish, and detach. It is the concrete
:class:`~arcavex.kernel.api.OrchestratorProtocol` the facade delegates to, so the kernel never
imports a service or a built-in. Every public method returns a versioned kernel result model
and never raises across the boundary.

Determinism is the invariant here (§8.1): a run captures the resolved data snapshot and all
input hashes so a rerun compiles the exact same document; runs render into a private staging
directory first and move into a unique run directory only once every output succeeded, so a
failed render never leaves a partial run; and batch jobs are fully independent, so running them
in parallel produces byte-identical output to running them serially.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from arcavex.kernel.api import (
    BatchEntry,
    BatchReport,
    CompileResult,
    DetachReport,
    DiffReport,
    ProjectResult,
    ProjectStatusReport,
    PublishReport,
    RerunReport,
    RunInfo,
    RunListReport,
    RunReport,
    UpgradeOutputDiff,
    UpgradeReport,
)
from arcavex.kernel.diagnostics import Diagnostic, diagnostic, has_errors
from arcavex.kernel.ir.models import CompiledDocument, CompiledGroup, CompiledImage, CompiledNode
from arcavex.services.assets import AssetStore
from arcavex.services.fsutil import home_dir
from arcavex.services.imaging import dssim_files
from arcavex.services.library import Library, is_library_ref
from arcavex.services.projects import Project, ProjectService, template_stem
from arcavex.services.runs import (
    AssetProvenance,
    InputRef,
    RunManifest,
    RunOutput,
    RunStore,
    diff_runs,
    font_provenance,
    format_run_id,
    platform_tag,
    short_hash,
    utc_now,
)

# (document, output_path, dpi, debug) -> (report-with-sha256, layout warnings)
RenderFn = Callable[[CompiledDocument, Path, "int | None", bool], "tuple[Any, list[Diagnostic]]"]
Clock = Callable[[], datetime]
# ((project_dir_str, dpi)) -> a serializable render result dict; runs in a worker process.
BatchWorker = Callable[["tuple[str, int | None]"], "dict[str, Any]"]

IR_VERSION = "1.0"


def _output_name(stem: str, fmt: str, locale: str | None) -> str:
    """Return the run output filename ``<stem>.<format>[.<locale>].png`` (§6.3)."""
    locale_seg = f".{locale}" if locale else ""
    return f"{stem}.{fmt}{locale_seg}.png"


@dataclass
class _Rendered:
    """One rendered target staged for a run: its file, target, hashes, and provenance."""

    fmt: str
    locale: str | None
    name: str
    staged_path: Path
    sha256: str
    width: int
    height: int
    bytes: int
    seed: int
    data_hash: str
    snapshot: dict[str, Any]
    assets: list[AssetProvenance]
    diagnostics: list[Diagnostic] = field(default_factory=list)


class Orchestrator:
    """Drives projects, the library, and provenance on top of the injected render pipeline."""

    def __init__(
        self,
        compiler: Any,
        render_fn: RenderFn,
        engine_version: str,
        *,
        library: Library | None = None,
        projects: ProjectService | None = None,
        run_store: RunStore | None = None,
        asset_root: Path | None = None,
        clock: Clock = utc_now,
        dssim_fn: Callable[[Path, Path], float | None] = dssim_files,
        batch_worker: BatchWorker | None = None,
    ) -> None:
        """Wire the orchestrator with its compiler, renderer, services, clock, and batch worker."""
        self._compiler = compiler
        self._render = render_fn
        self._engine_version = engine_version
        self._library = library or Library()
        self._projects = projects or ProjectService(self._library)
        self._runs = run_store or RunStore()
        self._asset_root = asset_root if asset_root is not None else home_dir() / "assets"
        self._clock = clock
        self._dssim = dssim_fn
        # A picklable module-level worker (bootstrap-provided) that renders one project in an
        # isolated process; without it, batch runs serially in-process.
        self._batch_worker = batch_worker

    # -------------------------------------------------------------------- projects
    def create_project(
        self,
        target: Path,
        name: str,
        template_ref: str,
        style: str | None,
        formats: list[str] | None,
        locales: list[str] | None,
    ) -> ProjectResult:
        project = self._projects.create(
            target, name, template_ref, style=style, formats=formats, locales=locales
        )
        m = project.manifest
        return ProjectResult(
            ok=True,
            path=str(project.root),
            name=m.name,
            template=m.template,
            style=m.style,
            formats=list(m.formats),
            locales=list(m.locales),
            status=m.status,
        )

    def project_status(
        self, start: Path | None, project: Path | None
    ) -> ProjectStatusReport:
        proj = self._projects.resolve(start, project)
        return self._status_report(proj)

    def clone_project(
        self, start: Path | None, project: Path | None, target: Path, name: str
    ) -> ProjectResult:
        proj = self._projects.resolve(start, project)
        cloned = self._projects.clone(proj, target, name)
        m = cloned.manifest
        return ProjectResult(
            ok=True,
            path=str(cloned.root),
            name=m.name,
            template=m.template,
            style=m.style,
            formats=list(m.formats),
            locales=list(m.locales),
            status=m.status,
        )

    def set_project_status(
        self, start: Path | None, project: Path | None, status: str
    ) -> ProjectStatusReport:
        proj = self._projects.resolve(start, project)
        updated = self._projects.set_status(proj, status)
        return self._status_report(updated)

    def _status_report(self, project: Project) -> ProjectStatusReport:
        m = project.manifest
        runs = len(self._runs.list_runs(project.outputs_dir))
        return ProjectStatusReport(
            ok=True,
            name=m.name,
            template=m.template,
            style=m.style,
            status=m.status,
            formats=list(m.formats),
            locales=list(m.locales),
            tags=list(m.tags),
            data=m.data,
            root=str(project.root),
            runs=runs,
        )

    # -------------------------------------------------------------------- rendering
    def render_project(
        self,
        start: Path | None,
        project: Path | None,
        formats: list[str] | None,
        locales: list[str] | None,
        dpi: int | None,
    ) -> RunReport:
        proj = self._projects.resolve(start, project)
        template_dir, ref, is_lib = self._projects.resolve_template(proj)
        patch_ops, patch_file = self._projects.load_project_patch(proj)
        targets = self._projects.render_targets(proj, formats, locales)
        if not targets:
            return RunReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-PRJ-002",
                        "Project declares no formats to render",
                        file=str(proj.project_file),
                        hint="Add at least one format to 'formats:' in project.yaml.",
                    )
                ],
            )
        return self._execute_run(
            kind="project",
            project_name=proj.manifest.name,
            stem=proj.manifest.name,
            template_dir=template_dir,
            template_ref=ref,
            is_library=is_lib,
            style_ref=proj.manifest.style,
            data_path=proj.data_path,
            targets=targets,
            patch_ops=patch_ops,
            patch_file=patch_file,
            dpi=dpi,
            outputs_root=proj.outputs_dir,
        )

    def record_render(
        self,
        template: Path,
        data: Path | None,
        format_name: str | None,
        locale: str | None,
        style: str | None,
        dpi: int | None,
        outputs_root: Path | None,
    ) -> RunReport:
        template = Path(template)
        formats = self._compiler.list_formats(template)
        if format_name is not None:
            targets: list[tuple[str, str | None]] = [(format_name, locale)]
        elif len(formats) == 1:
            targets = [(formats[0], locale)]
        else:
            return RunReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-TPL-021",
                        "No format specified and the template defines several",
                        file=str(template),
                        hint=f"Pass --format with one of: {', '.join(formats)}",
                    )
                ],
            )
        stem = template.stem if template.suffix else template.name
        root = Path(outputs_root) if outputs_root is not None else Path.cwd() / "outputs"
        return self._execute_run(
            kind="direct",
            project_name=None,
            stem=stem,
            template_dir=template,
            template_ref=str(template.resolve()),
            is_library=False,
            style_ref=style,
            data_path=data,
            targets=targets,
            patch_ops=None,
            patch_file=None,
            dpi=dpi,
            outputs_root=root,
        )

    def _execute_run(
        self,
        *,
        kind: str,
        project_name: str | None,
        stem: str,
        template_dir: Path,
        template_ref: str,
        is_library: bool,
        style_ref: str | None,
        data_path: Path | None,
        targets: list[tuple[str, str | None]],
        patch_ops: list[Any] | None,
        patch_file: Path | None,
        dpi: int | None,
        outputs_root: Path,
        resolved_snapshots: dict[str, dict[str, Any]] | None = None,
    ) -> RunReport:
        staging = Path(tempfile.mkdtemp(prefix="arcavex-run-"))
        try:
            rendered, diags, template_hash, style_hash = self._render_all(
                stem=stem,
                template_dir=template_dir,
                style_ref=style_ref,
                data_path=data_path,
                targets=targets,
                patch_ops=patch_ops,
                patch_file=patch_file,
                dpi=dpi,
                staging=staging,
                resolved_snapshots=resolved_snapshots,
            )
            if has_errors(diags) or rendered is None:
                # Clean cancellation: no run directory, no partial outputs published (§8.3).
                return RunReport(ok=False, diagnostics=diags)
            manifest, run_dir = self._finalize(
                kind=kind,
                project_name=project_name,
                template_ref=template_ref,
                template_hash=template_hash,
                is_library=is_library,
                style_ref=style_ref,
                style_hash=style_hash,
                dpi=dpi,
                rendered=rendered,
                outputs_root=outputs_root,
                extra_diagnostics=[d for d in diags if not d.is_error()],
            )
            return RunReport(
                ok=True,
                run_id=manifest.run_id,
                run_dir=str(run_dir),
                outputs=[str(run_dir / o.name) for o in manifest.outputs],
                diagnostics=list(manifest.diagnostics),
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _render_all(
        self,
        *,
        stem: str,
        template_dir: Path,
        style_ref: str | None,
        data_path: Path | None,
        targets: list[tuple[str, str | None]],
        patch_ops: list[Any] | None,
        patch_file: Path | None,
        dpi: int | None,
        staging: Path,
        resolved_snapshots: dict[str, dict[str, Any]] | None,
    ) -> tuple[list[_Rendered] | None, list[Diagnostic], str, str | None]:
        rendered: list[_Rendered] = []
        diags: list[Diagnostic] = []
        template_hash = ""
        style_hash: str | None = None
        store = AssetStore(self._asset_root)
        for fmt, locale in targets:
            snapshot = None
            if resolved_snapshots is not None:
                snapshot = resolved_snapshots.get(_locale_key(locale))
            result: CompileResult = self._compiler.compile(
                template_dir,
                None if snapshot is not None else data_path,
                fmt,
                locale,
                style_ref,
                resolved_data=snapshot,
                project_patch=patch_ops,
                project_patch_file=patch_file,
            )
            diags.extend(result.diagnostics)
            if result.document is None or has_errors(result.diagnostics):
                return None, diags, template_hash, style_hash
            template_hash = result.template_hash or template_hash
            style_hash = result.style_hash
            name = _output_name(stem, fmt, locale)
            report, warnings = self._render(result.document, staging / name, dpi, False)
            diags.extend(warnings)
            assets = _collect_assets(result.document, template_dir, store)
            rendered.append(
                _Rendered(
                    fmt=fmt,
                    locale=locale,
                    name=name,
                    staged_path=staging / name,
                    sha256=report.content_sha256,
                    width=result.document.canvas.width_px,
                    height=result.document.canvas.height_px,
                    bytes=report.bytes_written,
                    seed=result.document.seed,
                    data_hash=result.data_hash or "",
                    snapshot=result.resolved_data or {},
                    assets=assets,
                )
            )
        return rendered, diags, template_hash, style_hash

    def _finalize(
        self,
        *,
        kind: str,
        project_name: str | None,
        template_ref: str,
        template_hash: str,
        is_library: bool,
        style_ref: str | None,
        style_hash: str | None,
        dpi: int | None,
        rendered: list[_Rendered],
        outputs_root: Path,
        extra_diagnostics: list[Diagnostic],
    ) -> tuple[RunManifest, Path]:
        fingerprint = short_hash(
            {
                "template": template_hash,
                "style": style_hash,
                "dpi": dpi,
                "targets": sorted(
                    [r.fmt, r.locale or "", r.data_hash] for r in rendered
                ),
            }
        )
        when = self._clock()
        run_id = format_run_id(when, fingerprint)
        run_dir, final_id = self._runs.new_run_dir(outputs_root, run_id)
        for r in rendered:
            shutil.move(str(r.staged_path), str(run_dir / r.name))
        snapshots: dict[str, dict[str, Any]] = {}
        assets: dict[str, AssetProvenance] = {}
        outputs: list[RunOutput] = []
        for r in rendered:
            snapshots[_locale_key(r.locale)] = r.snapshot
            for a in r.assets:
                assets[a.sha256] = a
            outputs.append(
                RunOutput(
                    name=r.name,
                    format=r.fmt,
                    locale=r.locale,
                    sha256=r.sha256,
                    width=r.width,
                    height=r.height,
                    bytes=r.bytes,
                    seed=r.seed,
                    data_hash=r.data_hash,
                )
            )
        fonts_hash, fonts = font_provenance()
        manifest = RunManifest(
            run_id=final_id,
            created=when.isoformat(),
            engine_version=self._engine_version,
            platform=platform_tag(),
            ir_version=IR_VERSION,
            kind=kind,  # type: ignore[arg-type]
            project=project_name,
            template=InputRef(ref=template_ref, hash=template_hash),
            template_is_library=is_library,
            style=InputRef(ref=style_ref, hash=style_hash) if style_ref is not None else None,
            dpi=dpi,
            outputs=outputs,
            assets=sorted(assets.values(), key=lambda a: a.sha256),
            fonts_hash=fonts_hash,
            fonts=fonts,
            diagnostics=extra_diagnostics,
            resolved_data=snapshots,
        )
        self._runs.write_manifest(run_dir, manifest)
        return manifest, run_dir

    # -------------------------------------------------------------------- runs & diff
    def list_runs(self, start: Path | None, project: Path | None) -> RunListReport:
        proj = self._projects.resolve(start, project)
        infos = [
            RunInfo(
                run_id=m.run_id,
                created=m.created,
                kind=m.kind,
                project=m.project,
                engine_version=m.engine_version,
                platform=m.platform,
                outputs=[o.name for o in m.outputs],
            )
            for m in self._runs.list_runs(proj.outputs_dir)
        ]
        return RunListReport(ok=True, runs=infos)

    def diff(self, run_a: Path, run_b: Path) -> DiffReport:
        return diff_runs(Path(run_a), Path(run_b), self._runs, self._dssim)

    def rerun(self, run_dir: Path) -> RerunReport:
        run_dir = Path(run_dir)
        manifest = self._runs.read_manifest(run_dir)
        engine_match = manifest.engine_version == self._engine_version
        platform_match = manifest.platform == platform_tag()
        template_dir = self._resolve_manifest_template(manifest, run_dir)
        patch_ops, patch_file = self._reload_project_patch(manifest, run_dir)
        targets = [(o.format, o.locale) for o in manifest.outputs]
        outputs_root = run_dir.parent
        staging = Path(tempfile.mkdtemp(prefix="arcavex-rerun-"))
        try:
            rendered, diags, template_hash, style_hash = self._render_all(
                stem=_stem_from_outputs(manifest),
                template_dir=template_dir,
                style_ref=manifest.style.ref if manifest.style else None,
                data_path=None,
                targets=targets,
                patch_ops=patch_ops,
                patch_file=patch_file,
                dpi=manifest.dpi,
                staging=staging,
                resolved_snapshots=manifest.resolved_data,
            )
            if rendered is None or has_errors(diags):
                return RerunReport(
                    ok=False, source_run=manifest.run_id, diagnostics=diags,
                    engine_match=engine_match, platform_match=platform_match,
                )
            mismatches = self._byte_mismatches(manifest, rendered)
            reproduced = not mismatches and engine_match and platform_match
            new_manifest, new_dir = self._finalize(
                kind=manifest.kind,
                project_name=manifest.project,
                template_ref=manifest.template.ref,
                template_hash=template_hash,
                is_library=manifest.template_is_library,
                style_ref=manifest.style.ref if manifest.style else None,
                style_hash=style_hash,
                dpi=manifest.dpi,
                rendered=rendered,
                outputs_root=outputs_root,
                extra_diagnostics=[d for d in diags if not d.is_error()],
            )
            self._write_reproduction(new_dir, manifest, reproduced, mismatches, engine_match)
            return RerunReport(
                ok=True,
                source_run=manifest.run_id,
                run_id=new_manifest.run_id,
                run_dir=str(new_dir),
                reproduced=reproduced,
                engine_match=engine_match,
                platform_match=platform_match,
                mismatches=mismatches,
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _byte_mismatches(
        self, manifest: RunManifest, rendered: list[_Rendered]
    ) -> list[str]:
        want = {o.name: o.sha256 for o in manifest.outputs}
        return sorted(r.name for r in rendered if want.get(r.name) != r.sha256)

    def _write_reproduction(
        self,
        new_dir: Path,
        source: RunManifest,
        reproduced: bool,
        mismatches: list[str],
        engine_match: bool,
    ) -> None:
        import json

        from arcavex.services.fsutil import atomic_write_text

        report = {
            "source_run": source.run_id,
            "reproduced": reproduced,
            "engine_match": engine_match,
            "engine_version_original": source.engine_version,
            "engine_version_now": self._engine_version,
            "platform_original": source.platform,
            "platform_now": platform_tag(),
            "mismatched_outputs": mismatches,
        }
        atomic_write_text(
            new_dir / "reproduction.json", json.dumps(report, ensure_ascii=False, indent=2)
        )

    def _resolve_manifest_template(self, manifest: RunManifest, run_dir: Path) -> Path:
        ref = manifest.template.ref
        if manifest.template_is_library:
            return self._library.resolve(ref).path
        path = Path(ref)
        if path.is_absolute():
            return path if path.is_dir() else path.parent
        # Project-relative path template: resolve against the project root (outputs/<run>/..).
        base = run_dir.parents[1] if manifest.kind == "project" else run_dir.parent
        resolved = (base / ref).resolve()
        return resolved if resolved.is_dir() else resolved.parent

    def _reload_project_patch(
        self, manifest: RunManifest, run_dir: Path
    ) -> tuple[list[Any] | None, Path | None]:
        if manifest.kind != "project":
            return None, None
        project_root = run_dir.parents[1]
        stem = template_stem(manifest.template.ref)
        patch_file = project_root / "overrides" / f"{stem}.patch.yaml"
        if not patch_file.is_file():
            return None, None
        from arcavex.services.template.loader import load_yaml

        raw = load_yaml(patch_file)
        return (list(raw), patch_file) if isinstance(raw, list) else (None, None)

    # -------------------------------------------------------------------- batch
    def batch_render(self, globs: list[str], jobs: int, dpi: int | None) -> BatchReport:
        """Render every matched project; parallel jobs are output-identical to serial (§8.1).

        Parallelism is process-based, not threaded: the compiler carries per-compile state and
        the shaper is not built for concurrent use, so jobs run in isolated processes (each with
        its own engine) rather than sharing mutable state. Because every job is fully independent
        and deterministic, and results are re-ordered to match the input order, a parallel batch
        produces byte-identical output to a serial one. Without an injected process worker (unit
        tests), jobs fall back to safe in-process serial execution.
        """
        project_dirs = _expand_project_globs(globs)
        if not project_dirs:
            return BatchReport(
                ok=False,
                jobs=jobs,
                diagnostics=[
                    diagnostic(
                        "ARC-PRJ-001",
                        "No projects matched the batch pattern(s)",
                        hint="Point 'batch' at directories that each contain a project.yaml.",
                    )
                ],
            )
        workers = max(1, jobs)
        if workers == 1 or self._batch_worker is None:
            entries = [self._render_project_entry(p, dpi) for p in project_dirs]
            return BatchReport(ok=all(e.ok for e in entries), jobs=1, entries=entries)
        payloads = [(str(p), dpi) for p in project_dirs]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            # map preserves input order, so entries are deterministic regardless of finish order.
            results = list(pool.map(self._batch_worker, payloads))
        entries = [
            _entry_from_worker(str(p), r)
            for p, r in zip(project_dirs, results, strict=True)
        ]
        return BatchReport(ok=all(e.ok for e in entries), jobs=workers, entries=entries)

    def _render_project_entry(self, project_dir: Path, dpi: int | None) -> BatchEntry:
        report = self.render_project(None, project_dir, None, None, dpi)
        return BatchEntry(
            project=str(project_dir),
            ok=report.ok,
            run_id=report.run_id,
            run_dir=report.run_dir,
            outputs=report.outputs,
            diagnostics=report.diagnostics,
        )

    # -------------------------------------------------------------------- upgrade
    def upgrade_project(
        self, start: Path | None, project: Path | None, to_version: str, apply: bool
    ) -> UpgradeReport:
        proj = self._projects.resolve(start, project)
        ref = proj.manifest.template
        if not is_library_ref(ref):
            return UpgradeReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-PRJ-006",
                        "This project's template is a local path, not a library pin; "
                        "version upgrades are unavailable",
                        file=str(proj.project_file),
                        hint="Only projects pinned to a library 'name@version' can be upgraded.",
                    )
                ],
            )
        name, _, from_version = ref.partition("@")
        target = self._library.resolve(f"{name}@{to_version}")
        patch_ops, patch_file = self._projects.load_project_patch(proj)
        targets = self._projects.render_targets(proj)
        stale = self._stale_patch_paths(
            target.path, proj, targets, patch_ops, patch_file
        )
        outputs = self._upgrade_previews(
            proj, name, from_version, target, targets, patch_ops, patch_file
        )
        applied = False
        if apply:
            updated = proj.manifest.model_copy(update={"template": f"{name}@{to_version}"})
            self._projects.save(Project(root=proj.root, manifest=updated))
            applied = True
        return UpgradeReport(
            ok=True,
            from_version=from_version or None,
            to_version=to_version,
            stale_paths=stale,
            outputs=outputs,
            applied=applied,
        )

    def _stale_patch_paths(
        self,
        target_dir: Path,
        proj: Project,
        targets: list[tuple[str, str | None]],
        patch_ops: list[Any] | None,
        patch_file: Path | None,
    ) -> list[str]:
        if not patch_ops:
            return []
        stale: set[str] = set()
        for fmt, locale in targets:
            result = self._compiler.compile(
                target_dir, proj.data_path, fmt, locale, proj.manifest.style,
                project_patch=patch_ops, project_patch_file=patch_file,
            )
            for d in result.diagnostics:
                if d.code == "ARC-TPL-092" and d.source is not None and d.source.keypath:
                    stale.add(d.source.keypath)
        return sorted(stale)

    def _upgrade_previews(
        self,
        proj: Project,
        name: str,
        from_version: str,
        target: Any,
        targets: list[tuple[str, str | None]],
        patch_ops: list[Any] | None,
        patch_file: Path | None,
    ) -> list[UpgradeOutputDiff]:
        old_dir = self._library.resolve(f"{name}@{from_version}").path if from_version else None
        if old_dir is None:
            return []
        staging = Path(tempfile.mkdtemp(prefix="arcavex-upgrade-"))
        out: list[UpgradeOutputDiff] = []
        try:
            for fmt, locale in targets:
                name_png = _output_name(proj.manifest.name, fmt, locale)
                old_png = staging / f"old.{name_png}"
                new_png = staging / f"new.{name_png}"
                if not self._preview_one(
                    old_dir, proj, fmt, locale, patch_ops, patch_file, old_png
                ):
                    continue
                if not self._preview_one(
                    target.path, proj, fmt, locale, patch_ops, patch_file, new_png
                ):
                    continue
                out.append(
                    UpgradeOutputDiff(name=name_png, dssim=self._dssim(old_png, new_png))
                )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return out

    def _preview_one(
        self,
        template_dir: Path,
        proj: Project,
        fmt: str,
        locale: str | None,
        patch_ops: list[Any] | None,
        patch_file: Path | None,
        out_path: Path,
    ) -> bool:
        result = self._compiler.compile(
            template_dir, proj.data_path, fmt, locale, proj.manifest.style,
            project_patch=patch_ops, project_patch_file=patch_file,
        )
        if result.document is None or has_errors(result.diagnostics):
            return False
        self._render(result.document, out_path, None, False)
        return True

    # -------------------------------------------------------------------- library
    def publish_template(
        self, template: Path, name: str, version: str, set_default: bool
    ) -> PublishReport:
        resolved = self._library.publish(Path(template), name, version, set_default=set_default)
        default = self._library.index(name).default
        return PublishReport(
            ok=True, name=resolved.name, version=resolved.version,
            path=str(resolved.path), default=default,
        )

    def detach_template(self, start: Path | None, project: Path | None) -> DetachReport:
        proj = self._projects.resolve(start, project)
        ref = proj.manifest.template
        if not is_library_ref(ref):
            return DetachReport(
                ok=False,
                template=ref,
                diagnostics=[
                    diagnostic(
                        "ARC-PRJ-006",
                        "Project template is already a local path; nothing to detach",
                        file=str(proj.project_file),
                        hint="Detach applies only to a library 'name@version' pin.",
                    )
                ],
            )
        resolved = self._library.resolve(ref)
        dest = proj.root / "templates" / resolved.name
        if dest.exists():
            return DetachReport(
                ok=False,
                template=ref,
                diagnostics=[
                    diagnostic(
                        "ARC-PRJ-006",
                        f"Detach target already exists: {dest}",
                        file=str(dest),
                        hint="Remove the existing copy before detaching again.",
                    )
                ],
            )
        shutil.copytree(resolved.path, dest)
        rel = f"templates/{resolved.name}"
        updated = proj.manifest.model_copy(update={"template": rel})
        self._projects.save(Project(root=proj.root, manifest=updated))
        return DetachReport(
            ok=True,
            template=rel,
            path=str(dest),
            diagnostics=[
                diagnostic(
                    "ARC-PRJ-007",
                    "Template detached into the project; version upgrades are now disabled",
                    severity="warning",
                    file=str(proj.project_file),
                    hint="Edit the copied template directly; re-pin to a library version to "
                    "re-enable upgrades.",
                )
            ],
        )


def _entry_from_worker(project_dir: str, result: dict[str, Any]) -> BatchEntry:
    """Rebuild a :class:`BatchEntry` from a worker process's serializable result dict."""
    diags = [Diagnostic.model_validate(d) for d in result.get("diagnostics", [])]
    return BatchEntry(
        project=project_dir,
        ok=bool(result.get("ok")),
        run_id=result.get("run_id"),
        run_dir=result.get("run_dir"),
        outputs=list(result.get("outputs", [])),
        diagnostics=diags,
    )


def _locale_key(locale: str | None) -> str:
    """The snapshot/manifest key for a locale (``""`` for the base/no-locale render)."""
    return locale or ""


def _stem_from_outputs(manifest: RunManifest) -> str:
    """Recover the output filename stem from a manifest (project name or template stem)."""
    if manifest.project:
        return manifest.project
    if manifest.outputs:
        return manifest.outputs[0].name.split(".", 1)[0]
    return "output"


def _collect_assets(
    document: CompiledDocument, template_dir: Path, store: AssetStore
) -> list[AssetProvenance]:
    """Ingest and record every image asset a compiled document references."""
    paths: list[str] = []

    def visit(node: CompiledNode) -> None:
        if isinstance(node, CompiledImage):
            paths.append(node.asset_path)
        if isinstance(node, CompiledGroup):
            for child in node.children:
                visit(child)

    visit(document.root)
    out: list[AssetProvenance] = []
    seen: set[str] = set()
    for raw in paths:
        ref = store.ingest(Path(raw))
        if ref.sha256 in seen:
            continue
        seen.add(ref.sha256)
        try:
            rel = str(Path(raw).resolve().relative_to(Path(template_dir).resolve()))
        except ValueError:
            rel = Path(raw).name
        out.append(
            AssetProvenance(
                path=rel.replace("\\", "/"),
                sha256=ref.sha256,
                mime=ref.mime,
                width=ref.width,
                height=ref.height,
                bytes=ref.bytes,
            )
        )
    return out


def _expand_project_globs(globs: list[str]) -> list[Path]:
    """Expand glob patterns to the sorted, de-duplicated set of directories with a project.yaml."""
    from glob import glob as _glob

    found: dict[str, Path] = {}
    for pattern in globs:
        matches = _glob(pattern) or ([pattern] if Path(pattern).exists() else [])
        for match in matches:
            path = Path(match)
            if path.is_dir() and (path / "project.yaml").is_file():
                found[str(path.resolve())] = path
    return [found[k] for k in sorted(found)]

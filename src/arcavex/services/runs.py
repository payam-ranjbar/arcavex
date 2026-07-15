"""Run manifests, run directories, diff, and the rerun contract (spec §5.3).

A *run* is one recorded render — a project render (formats × locales) or a direct render with
``--record`` — materialized as ``outputs/<timestamp>_<shorthash>/`` holding a ``manifest.json``
and the output images. The manifest pins every input by hash (engine version, platform, IR
version, canonical template/style/data hashes, the resolved data snapshot, asset and font
hashes, seed, options) plus per-output content hashes and timings, so a run is fully
reproducible and comparable (§8.1). This module owns the manifest schema and its safe on-disk
handling; the render pipeline itself lives in the facade. Timestamps come from an injected
clock and never enter image bytes — reruns differ only in their surrounding run directory, not
in the rendered pixels.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from arcavex.kernel.api import DiffReport, MetadataDiff, OutputDiff
from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic
from arcavex.kernel.ir.canonical import canonical_hash
from arcavex.services.fsutil import atomic_write_text, sha256_file

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current UTC time (the default manifest clock)."""
    return datetime.now(UTC)


def platform_tag() -> str:
    """Return the OS/arch determinism tag, e.g. ``win-x86_64`` (matches the golden harness)."""
    import platform

    system = {"windows": "win", "darwin": "macos", "linux": "linux"}.get(
        platform.system().lower(), platform.system().lower()
    )
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine, machine
    )
    return f"{system}-{machine}"


# ------------------------------------------------------------------------- manifest models
class InputRef(BaseModel):
    """A recorded input: how it was referenced plus its canonical content hash."""

    model_config = ConfigDict(frozen=True)

    ref: str
    hash: str | None = None


class AssetProvenance(BaseModel):
    """One referenced image asset, pinned by content hash and header dimensions."""

    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    mime: str
    width: int
    height: int
    bytes: int


class FontProvenance(BaseModel):
    """One bundled font file, pinned by content hash (the render's font environment)."""

    model_config = ConfigDict(frozen=True)

    name: str
    sha256: str


class RunOutput(BaseModel):
    """One rendered image in a run: its filename, target, content hash, and dimensions."""

    model_config = ConfigDict(frozen=True)

    name: str
    format: str
    locale: str | None = None
    sha256: str
    width: int
    height: int
    bytes: int
    seed: int
    data_hash: str


class RunManifest(BaseModel):
    """The provenance record for one run (§5.3): every input by hash plus every output."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = MANIFEST_SCHEMA_VERSION
    run_id: str
    created: str
    engine_version: str
    platform: str
    ir_version: str
    kind: Literal["project", "direct"]
    project: str | None = None
    template: InputRef
    template_is_library: bool = False
    style: InputRef | None = None
    dpi: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    outputs: list[RunOutput] = Field(default_factory=list)
    assets: list[AssetProvenance] = Field(default_factory=list)
    fonts_hash: str = ""
    fonts: list[FontProvenance] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    # Resolved variable snapshots keyed by locale ("" for the base/no-locale render), the
    # authoritative data a rerun compiles from (§5.3).
    resolved_data: dict[str, dict[str, Any]] = Field(default_factory=dict)


# ------------------------------------------------------------------------------ run ids
def short_hash(manifest_inputs: dict[str, Any]) -> str:
    """Return a 6-hex content fingerprint for a run id from its canonical inputs.

    Derived from the inputs (template/style/data hashes and options), not the clock, so the
    same render always carries the same fingerprint while the timestamp distinguishes runs.
    """
    return canonical_hash(manifest_inputs)[:6]


def format_run_id(when: datetime, fingerprint: str) -> str:
    """Format a run id as ``YYYY-MM-DDTHH-MM-SSZ_<fingerprint>`` (filesystem-safe)."""
    stamp = when.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{stamp}_{fingerprint}"


class RunStore:
    """Reads and writes run directories and their manifests under a project's ``outputs/``."""

    def new_run_dir(self, outputs_root: Path, run_id: str) -> tuple[Path, str]:
        """Create and return a unique run directory and its final run id.

        Directory creation is the atomic uniqueness primitive: ``os.mkdir`` fails if the name
        exists, so two concurrent renders that computed the same base id get distinct suffixed
        directories and neither clobbers the other (§8.3).
        """
        outputs_root = Path(outputs_root)
        outputs_root.mkdir(parents=True, exist_ok=True)
        candidate = run_id
        suffix = 1
        while True:
            run_dir = outputs_root / candidate
            try:
                run_dir.mkdir()
                return run_dir, candidate
            except FileExistsError:
                suffix += 1
                candidate = f"{run_id}_{suffix}"

    def write_manifest(self, run_dir: Path, manifest: RunManifest) -> None:
        """Write ``manifest.json`` into a completed run directory atomically (write-once)."""
        import json

        payload = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
        atomic_write_text(Path(run_dir) / MANIFEST_NAME, payload)

    def read_manifest(self, run_dir: Path) -> RunManifest:
        """Load and validate a run's manifest, or raise ``ARC-RUN-001`` if it is missing/invalid."""
        path = Path(run_dir) / MANIFEST_NAME
        if not path.is_file():
            raise DiagnosticError(
                diagnostic(
                    "ARC-RUN-001",
                    f"No run manifest at {run_dir}",
                    file=str(run_dir),
                    hint="Point at a run directory produced by a recorded render "
                    "(outputs/<timestamp>_<hash>/).",
                )
            )
        try:
            return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - malformed manifest becomes a located error
            raise DiagnosticError(
                diagnostic(
                    "ARC-RUN-001",
                    f"Run manifest is malformed: {path}",
                    file=str(path),
                    hint="The manifest could not be parsed against the current schema.",
                )
            ) from exc

    def list_runs(self, outputs_root: Path) -> list[RunManifest]:
        """Return every readable run manifest under ``outputs_root``, newest run id first."""
        outputs_root = Path(outputs_root)
        if not outputs_root.is_dir():
            return []
        runs: list[RunManifest] = []
        for child in sorted(outputs_root.iterdir()):
            if not child.is_dir():
                continue
            if (child / MANIFEST_NAME).is_file():
                try:
                    runs.append(self.read_manifest(child))
                except DiagnosticError:
                    continue
        runs.sort(key=lambda m: m.run_id, reverse=True)
        return runs


# --------------------------------------------------------------------------------- diff
def diff_runs(
    run_a: Path,
    run_b: Path,
    store: RunStore,
    dssim_fn: Callable[[Path, Path], float | None],
) -> DiffReport:
    """Compare two run directories: per-output pixel/perceptual diff and metadata changes.

    Reads both manifests, matches outputs by filename, reports each output's byte-identity and
    (for common, same-shape outputs) its DSSIM via ``dssim_fn``, and separately lists the
    provenance fields that changed — template, style, data (per locale), engine, platform, dpi,
    and the font environment — so a viewer sees both *what looks different* and *why*.
    """
    a = store.read_manifest(run_a)
    b = store.read_manifest(run_b)
    outputs = _diff_outputs(Path(run_a), Path(run_b), a, b, dssim_fn)
    metadata = _diff_metadata(a, b)
    return DiffReport(
        ok=True, run_a=a.run_id, run_b=b.run_id, outputs=outputs, metadata=metadata
    )


def _diff_outputs(
    dir_a: Path,
    dir_b: Path,
    a: RunManifest,
    b: RunManifest,
    dssim_fn: Callable[[Path, Path], float | None],
) -> list[OutputDiff]:
    by_a = {o.name: o for o in a.outputs}
    by_b = {o.name: o for o in b.outputs}
    diffs: list[OutputDiff] = []
    for name in sorted(set(by_a) | set(by_b)):
        oa, ob = by_a.get(name), by_b.get(name)
        if oa is None or ob is None:
            diffs.append(OutputDiff(name=name, in_a=oa is not None, in_b=ob is not None))
            continue
        identical = oa.sha256 == ob.sha256
        score = 0.0 if identical else dssim_fn(dir_a / name, dir_b / name)
        diffs.append(
            OutputDiff(name=name, in_a=True, in_b=True, identical=identical, dssim=score)
        )
    return diffs


def _diff_metadata(a: RunManifest, b: RunManifest) -> list[MetadataDiff]:
    out: list[MetadataDiff] = []

    def cmp(field: str, va: str | None, vb: str | None) -> None:
        if va != vb:
            out.append(MetadataDiff(field=field, a=va, b=vb))

    cmp("template", _ref(a.template), _ref(b.template))
    cmp("template.hash", a.template.hash, b.template.hash)
    cmp("style", _ref(a.style), _ref(b.style))
    cmp("engine_version", a.engine_version, b.engine_version)
    cmp("platform", a.platform, b.platform)
    cmp("ir_version", a.ir_version, b.ir_version)
    cmp("dpi", _s(a.dpi), _s(b.dpi))
    cmp("fonts", a.fonts_hash, b.fonts_hash)
    for locale in sorted(set(a.resolved_data) | set(b.resolved_data)):
        ha = canonical_hash(a.resolved_data[locale]) if locale in a.resolved_data else None
        hb = canonical_hash(b.resolved_data[locale]) if locale in b.resolved_data else None
        cmp(f"data[{locale or '-'}]", ha, hb)
    return out


def _ref(ref: InputRef | None) -> str | None:
    return ref.ref if ref is not None else None


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


# ---------------------------------------------------------------------------- fonts
def font_provenance() -> tuple[str, list[FontProvenance]]:
    """Return ``(fonts_hash, [FontProvenance…])`` for the bundled font environment.

    The whole bundled set is captured, not only referenced families, because deterministic
    shaping fallback may consult any bundled font — so the reproducible input is the set. The
    combined ``fonts_hash`` is the single field a manifest and a diff compare.
    """
    from arcavex.services.text.service import find_font_dirs

    entries: list[FontProvenance] = []
    seen: set[str] = set()
    for directory in find_font_dirs():
        for path in sorted(directory.glob("*.ttf")):
            if path.name in seen:
                continue
            seen.add(path.name)
            entries.append(FontProvenance(name=path.name, sha256=sha256_file(path)))
    entries.sort(key=lambda f: f.name)
    combined = canonical_hash([[f.name, f.sha256] for f in entries])
    return combined, entries


def is_run_dir(path: Path) -> bool:
    """Whether ``path`` looks like a run directory (holds a manifest)."""
    return (Path(path) / MANIFEST_NAME).is_file()

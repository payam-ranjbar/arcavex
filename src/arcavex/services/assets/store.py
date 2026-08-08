"""Content-addressed asset store (CAS) with decode guards and sidecar metadata (spec §4.7).

Assets ingest by SHA-256 into ``objects/ab/cdef…`` and carry a JSON sidecar recording mime,
dimensions, source byte count, and free-form annotations. Ingestion is idempotent and atomic:
the same bytes always land at the same path, and an existing object is never rewritten, so two
concurrent renders ingesting the same asset cannot corrupt it. Decode guards (max source
bytes, max decoded pixels, format allowlist) are enforced against the file *header* before any
full decode, per the spec's rule that decompress-then-check is a security bug.

This is the minimal CAS the provenance system needs now: it records asset hashes and metadata
for run manifests. The derived-variant LRU cache (downscaled thumbnails) is deferred to Phase
7; only ingestion, sidecars, and the decode guards live here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from arcavex.kernel.contracts.types import DecodeGuards
from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.services.assets.alpha import opaque_box
from arcavex.services.assets.probe import ALLOWED_MIME, probe_image
from arcavex.services.fsutil import atomic_write_text, sha256_bytes


class AssetRef(BaseModel):
    """A CAS-resolved asset: its content hash, media type, dimensions, and byte size.

    This is what a run manifest records for each referenced asset, so the exact image bytes are
    pinned by hash and a diff can report an asset change (§5.3).
    """

    model_config = ConfigDict(frozen=True)

    sha256: str
    mime: str
    width: int
    height: int
    bytes: int
    # ``(x, y, width, height)`` of the opaque pixels; None when the image is fully transparent,
    # undecodable, or was ingested before this field existed. Defaulted so those sidecars parse.
    opaque_bbox: tuple[int, int, int, int] | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)


class AssetStore:
    """Ingests assets by content hash into a CAS rooted at ``objects/`` under ``root``."""

    def __init__(self, root: Path, guards: DecodeGuards | None = None) -> None:
        """Bind the store to its ``root`` directory and its decode ``guards``."""
        self._root = Path(root)
        self._guards = guards or DecodeGuards()

    @property
    def objects_dir(self) -> Path:
        """The ``objects/`` subdirectory holding content-addressed blobs."""
        return self._root / "objects"

    def ingest(self, path: Path) -> AssetRef:
        """Ingest the image at ``path`` into the CAS and return its :class:`AssetRef`.

        Enforces the decode guards against the header before hashing, writes the blob and its
        sidecar atomically (idempotently), and returns the reference. Raises ``ARC-AST-001`` if
        the file is missing, ``ARC-AST-002`` if it is not a decodable supported image, and
        ``ARC-AST-003`` if it exceeds a decode guard.
        """
        path = Path(path)
        if not path.is_file():
            raise DiagnosticError(
                diagnostic(
                    "ARC-AST-001",
                    f"Image asset not found: {path}",
                    file=str(path),
                    hint="Check the path exists and is readable.",
                )
            )
        size = path.stat().st_size
        if size > self._guards.max_source_bytes:
            raise self._guard_error(
                path, f"source is {size} bytes, over the {self._guards.max_source_bytes} cap"
            )
        data = path.read_bytes()
        probe = probe_image(data, source=str(path))
        if probe.mime not in ALLOWED_MIME:
            raise self._guard_error(path, f"format {probe.mime!r} is not allowed")
        if probe.pixels > self._guards.max_pixels:
            raise self._guard_error(
                path,
                f"{probe.width}×{probe.height} = {probe.pixels} pixels, "
                f"over the {self._guards.max_pixels} cap",
            )
        digest = sha256_bytes(data)
        box = opaque_box(path)
        ref = AssetRef(
            sha256=digest,
            mime=probe.mime,
            width=probe.width,
            height=probe.height,
            bytes=size,
            opaque_bbox=box.as_tuple() if box is not None else None,
        )
        self._persist(digest, data, ref)
        return ref

    def annotate(self, sha256: str, annotations: dict[str, Any]) -> AssetRef:
        """Merge ``annotations`` into a stored asset's sidecar and return the updated ref.

        Annotations are written once by a human (or an AI after *looking* at the image) and
        consumed by template expressions; perception never happens at render time (§4.7).
        """
        sidecar = self._sidecar_path(sha256)
        if not sidecar.is_file():
            raise DiagnosticError(
                diagnostic(
                    "ARC-AST-001",
                    f"No ingested asset with hash {sha256}",
                    hint="Ingest the asset before annotating it.",
                )
            )
        import json

        current = AssetRef.model_validate_json(sidecar.read_text(encoding="utf-8"))
        merged = {**current.annotations, **annotations}
        updated = current.model_copy(update={"annotations": merged})
        atomic_write_text(sidecar, json.dumps(updated.model_dump(mode="json"), ensure_ascii=False))
        return updated

    # -------------------------------------------------------------------- internals
    def _object_path(self, digest: str) -> Path:
        return self.objects_dir / digest[:2] / digest[2:]

    def _sidecar_path(self, digest: str) -> Path:
        obj = self._object_path(digest)
        return obj.with_name(obj.name + ".json")

    def _persist(self, digest: str, data: bytes, ref: AssetRef) -> None:
        import json

        obj = self._object_path(digest)
        if not obj.exists():
            # Content-addressed: identical bytes always hash here, so writing atomically and
            # only when absent makes ingestion idempotent and safe under concurrent renders.
            from arcavex.services.fsutil import atomic_write_bytes

            atomic_write_bytes(obj, data)
        sidecar = self._sidecar_path(digest)
        if not sidecar.exists():
            atomic_write_text(
                sidecar, json.dumps(ref.model_dump(mode="json"), ensure_ascii=False)
            )

    def _guard_error(self, path: Path, detail: str) -> DiagnosticError:
        return DiagnosticError(
            diagnostic(
                "ARC-AST-003",
                f"Image asset exceeds a decode guard: {path.name} ({detail})",
                file=str(path),
                hint=(
                    "Reduce the image size or dimensions; decode guards protect against runaway "
                    "decode work and are enforced before the image is decompressed."
                ),
            )
        )

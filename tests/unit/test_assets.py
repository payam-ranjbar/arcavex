"""Asset CAS tests: ingest-by-hash, idempotency, sidecars, decode guards, annotations."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from arcavex.kernel.contracts.types import DecodeGuards
from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.services.assets import AssetStore, probe_image

REPO_ROOT = Path(__file__).resolve().parents[2]
LOGO = REPO_ROOT / "examples" / "hello-poster" / "logo.png"


def _png_bytes(width: int, height: int) -> bytes:
    """Build a minimal valid single-pixel-row PNG of the given declared dimensions."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"\x00" + b"\x00\x00\x00" * width
    idat = zlib.compress(raw * height)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_probe_reads_png_dimensions() -> None:
    probe = probe_image(_png_bytes(320, 200), source="mem.png")
    assert (probe.mime, probe.width, probe.height) == ("image/png", 320, 200)


def test_probe_rejects_unknown_format() -> None:
    with pytest.raises(DiagnosticError) as exc:
        probe_image(b"not an image at all", source="junk.bin")
    assert exc.value.diagnostics[0].code == "ARC-AST-002"


def test_ingest_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "assets")
    ref1 = store.ingest(LOGO)
    ref2 = store.ingest(LOGO)
    assert ref1.sha256 == ref2.sha256
    obj = store.objects_dir / ref1.sha256[:2] / ref1.sha256[2:]
    assert obj.is_file()
    assert obj.with_name(obj.name + ".json").is_file()
    assert ref1.mime == "image/png" and ref1.width > 0 and ref1.height > 0


def test_decode_guard_rejects_too_many_pixels(tmp_path: Path) -> None:
    big = tmp_path / "big.png"
    big.write_bytes(_png_bytes(5000, 5000))  # 25 MP declared in the header
    store = AssetStore(tmp_path / "assets", guards=DecodeGuards(max_pixels=1_000_000))
    with pytest.raises(DiagnosticError) as exc:
        store.ingest(big)
    assert exc.value.diagnostics[0].code == "ARC-AST-003"


def test_decode_guard_rejects_too_many_bytes(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "assets", guards=DecodeGuards(max_source_bytes=10))
    with pytest.raises(DiagnosticError) as exc:
        store.ingest(LOGO)
    assert exc.value.diagnostics[0].code == "ARC-AST-003"


def test_annotate_merges_into_sidecar(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "assets")
    ref = store.ingest(LOGO)
    updated = store.annotate(ref.sha256, {"facing": "left", "focal_point": [0.5, 0.3]})
    assert updated.annotations["facing"] == "left"
    reloaded = store.annotate(ref.sha256, {"tag": "logo"})
    assert reloaded.annotations["facing"] == "left" and reloaded.annotations["tag"] == "logo"
